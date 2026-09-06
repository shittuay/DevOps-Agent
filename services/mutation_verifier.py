"""Synchronous read-back verification for creating and deleting tools
(Execution Integrity rule 2 — see docs/execution-integrity.md).

The agent must never report a create or a delete as done on the strength of
the mutating call's own response — cloud reads lag writes, and a
fabricated-looking success is indistinguishable from a real one. After a
create/delete tool returns success, ``verify_mutation`` calls the resource's
dedicated *read* tool a few times with a short backoff and annotates the
result:

  {'_verification': {'status': 'confirmed',   'action': 'create'|'delete', 'resource_id', 'via', ...}}
  {'_verification': {'status': 'unconfirmed', 'action': 'create'|'delete', 'resource_id', 'via', 'message'}}

``status == 'unconfirmed'`` is NOT "the operation failed" — for a create it
means the read hasn't caught up; for a delete it means the read still shows
the resource (often it is mid-shutdown) or the read itself is failing. The
``message`` tells the model exactly what to say.

Kept dependency-free and side-effect-free (``call_tool`` and ``sleep`` are
injected) so it unit-tests without a cloud account or the agent.
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable, Dict, Optional

# AWS resource ids: <prefix>-<8-17 hex>. Tighter than a bare startswith so a
# tag value like "i-am-a-thing" is not mistaken for an instance id.
_AWS_ID_RE = re.compile(r'^[a-z]+-[0-9a-f]{8,17}$')

# Backoff between read-back attempts, in seconds. First attempt is immediate
# (0), then 1 → 2 → 5 → 7 — ~15s total wall time, 5 attempts. Deliberately not
# the 60s the original spec suggested: the chat turn is held open by the
# keep-alive but every extra second is a slower reply.
DEFAULT_BACKOFF = (0, 1, 2, 5, 7)

# Max create/delete tools verified per turn — a turn that touches 10 instances
# should not add 150s. The rest are recorded in the registry unverified.
MAX_VERIFICATIONS_PER_TURN = 3

# AWS error codes that unambiguously mean "this resource does not exist".
# A read that fails with anything else (AccessDenied, Throttling, …) is
# "unknown", never "gone" — the "cannot read the account vs. a finding" trap.
_NOT_FOUND_CODES = {
    'InvalidGroup.NotFound', 'InvalidSecurityGroupID.NotFound',
    'InvalidVpcID.NotFound', 'InvalidVpcId.NotFound',
    'InvalidInstanceID.NotFound',
    'DBInstanceNotFound', 'DBInstanceNotFoundFault',
    'NoSuchBucket', 'NoSuchEntity',
    'ResourceNotFoundException', 'NotFoundException', 'ResourceNotFound',
}

# EC2 instance states that mean the terminate took effect (still visible in
# describe-instances for up to an hour, but the delete is not in question).
_EC2_TERMINAL_STATES = {'shutting-down', 'terminated'}


class _CreateSpec:
    __slots__ = ('read_tool', 'id_prefix', 'input_key', 'read_kwargs')

    def __init__(self, read_tool, *, id_prefix=None, input_key=None, read_kwargs=None):
        self.read_tool = read_tool
        self.id_prefix = id_prefix
        self.input_key = input_key
        self.read_kwargs = read_kwargs or (lambda rid, ti: {})


class _DeleteSpec:
    __slots__ = ('read_tool', 'id_prefix', 'input_key', 'read_kwargs', 'gone', 'applies')

    def __init__(self, read_tool, *, gone, id_prefix=None, input_key=None,
                 read_kwargs=None, applies=None):
        self.read_tool = read_tool
        self.gone = gone                     # (read_result, rid) -> 'gone'|'present'|'unknown'
        self.id_prefix = id_prefix
        self.input_key = input_key
        self.read_kwargs = read_kwargs or (lambda rid, ti: {})
        self.applies = applies or (lambda ti: True)


# ---- create specs: confirm the resource EXISTS -----------------------------

_CREATE_SPECS: Dict[str, _CreateSpec] = {
    'create_ec2_instance': _CreateSpec(
        'get_ec2_instances', id_prefix='i-',
        read_kwargs=lambda rid, ti: {'filters': {'instance-id': rid}}),
    'run_instances': _CreateSpec(
        'get_ec2_instances', id_prefix='i-',
        read_kwargs=lambda rid, ti: {'filters': {'instance-id': rid}}),
    'create_security_group': _CreateSpec(
        'describe_security_group', id_prefix='sg-',
        read_kwargs=lambda rid, ti: {'group_id': rid}),
    'create_vpc': _CreateSpec(
        'describe_vpc', id_prefix='vpc-',
        read_kwargs=lambda rid, ti: {'vpc_id': rid}),
    'create_rds_instance': _CreateSpec(
        'describe_rds_instance', input_key='db_instance_identifier',
        read_kwargs=lambda rid, ti: {'db_instance_identifier': rid}),
    'create_s3_bucket': _CreateSpec(
        'get_s3_bucket_info', input_key='bucket_name',
        read_kwargs=lambda rid, ti: {'bucket_name': rid}),
}


def _notfound(read: Any, extra_codes: tuple = ()) -> bool:
    if not isinstance(read, dict) or read.get('success') is True:
        return False
    code = read.get('error_code') or ''
    if code in _NOT_FOUND_CODES or code in extra_codes:
        return True
    return 'notfound' in str(read.get('error', '')).lower().replace(' ', '')


def _describe_gone(read: Any, rid: str) -> str:
    """For a describe-by-id read: gone iff it 404s; present iff it echoes the id."""
    if _notfound(read):
        return 'gone'
    if isinstance(read, dict) and read.get('success') is True:
        if any(v == rid for _k, v in _walk_strings(read)):
            return 'present'
    return 'unknown'


def _ec2_gone(read: Any, rid: str) -> str:
    if not isinstance(read, dict) or read.get('success') is not True:
        return _describe_gone(read, rid)  # a hard NotFound still counts as gone
    for inst in (read.get('instances') or []):
        if isinstance(inst, dict) and inst.get('instance_id') == rid:
            state = str(inst.get('state', '')).lower()
            return 'gone' if state in _EC2_TERMINAL_STATES else 'present'
    return 'gone'  # not in the filtered list at all


def _s3_gone(read: Any, rid: str) -> str:
    if not isinstance(read, dict) or read.get('success') is not True:
        return 'unknown'
    names = {b.get('name') for b in (read.get('buckets') or []) if isinstance(b, dict)}
    return 'present' if rid in names else 'gone'


_DELETE_SPECS: Dict[str, _DeleteSpec] = {
    'delete_ec2_instance': _DeleteSpec(
        'get_ec2_instances', gone=_ec2_gone, input_key='instance_id',
        read_kwargs=lambda rid, ti: {'filters': {'instance-id': rid}}),
    'manage_ec2_instance': _DeleteSpec(
        'get_ec2_instances', gone=_ec2_gone, input_key='instance_id',
        read_kwargs=lambda rid, ti: {'filters': {'instance-id': rid}},
        applies=lambda ti: str(ti.get('action', '')).lower() == 'terminate'),
    'delete_security_group': _DeleteSpec(
        'describe_security_group', gone=_describe_gone, input_key='group_id',
        id_prefix='sg-', read_kwargs=lambda rid, ti: {'group_id': rid}),
    'delete_vpc': _DeleteSpec(
        'describe_vpc', gone=_describe_gone, input_key='vpc_id',
        id_prefix='vpc-', read_kwargs=lambda rid, ti: {'vpc_id': rid}),
    'delete_rds_instance': _DeleteSpec(
        'describe_rds_instance', gone=_describe_gone, input_key='db_instance_identifier',
        read_kwargs=lambda rid, ti: {'db_instance_identifier': rid}),
    'delete_s3_bucket': _DeleteSpec(
        'list_s3_buckets', gone=_s3_gone, input_key='bucket_name',
        read_kwargs=lambda rid, ti: {}),
}

_RESOURCE_ID_KEYS = {
    'instanceid', 'instance_id', 'groupid', 'group_id', 'security_group_id',
    'vpcid', 'vpc_id', 'db_instance_identifier', 'dbinstanceidentifier',
    'bucketname', 'bucket_name', 'id', 'arn',
}


def is_verifiable(tool_name: str) -> bool:
    return tool_name in _CREATE_SPECS or tool_name in _DELETE_SPECS


def will_verify(tool_name: str, tool_input: dict) -> bool:
    """Like ``is_verifiable`` but also honours a delete spec's ``applies``
    predicate (e.g. ``manage_ec2_instance`` only verifies ``action='terminate'``)
    — so the caller only spends a per-turn verification slot when a read-back
    will actually run."""
    if tool_name in _CREATE_SPECS:
        return True
    dspec = _DELETE_SPECS.get(tool_name)
    return dspec is not None and dspec.applies(tool_input or {})


def _walk_strings(node: Any, depth: int = 0):
    if depth > 4:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str):
                yield k.lower(), v
            else:
                yield from _walk_strings(v, depth + 1)
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from _walk_strings(item, depth + 1)


def _resolve_id(spec, tool_input: dict, result: dict) -> Optional[str]:
    """The resource id to read back — from the result (creates) or the input (deletes)."""
    if getattr(spec, 'id_prefix', None):
        for _key, val in _walk_strings(result):
            if val.startswith(spec.id_prefix) and _AWS_ID_RE.match(val):
                return val
    if spec.input_key and tool_input.get(spec.input_key):
        v = tool_input[spec.input_key]
        if isinstance(v, (list, tuple)):
            return str(v[0]) if v else None
        return str(v)
    if spec.input_key:
        for key, val in _walk_strings(result):
            if key in _RESOURCE_ID_KEYS and val:
                return val
    return None


def _confirms_create(read_result: Any, resource_id: str) -> bool:
    """Create confirmed iff the read succeeded AND names the id back.

    Every create read tool echoes the queried id on success, so requiring the
    echo also guards against a read that returns success with an empty body.
    """
    if not isinstance(read_result, dict) or read_result.get('success') is not True:
        return False
    return any(val == resource_id for _key, val in _walk_strings(read_result))


def verify_mutation(
    tool_name: str,
    tool_input: dict,
    result: dict,
    *,
    call_tool: Callable[..., dict],
    sleep: Optional[Callable[[float], None]] = None,
    backoff: tuple = DEFAULT_BACKOFF,
) -> Optional[Dict[str, Any]]:
    """Read-back-verify a successful create/delete tool result.

    Returns an annotation dict for ``result['_verification']`` or ``None`` when
    the tool is not verifiable / not applicable / no resource id resolvable.
    Never raises — a read that errors just counts as "not confirmed yet".
    """
    tool_input = tool_input or {}
    create_spec = _CREATE_SPECS.get(tool_name)
    delete_spec = _DELETE_SPECS.get(tool_name)
    if delete_spec is not None and not delete_spec.applies(tool_input):
        return None
    spec = create_spec or delete_spec
    if spec is None:
        return None

    rid = _resolve_id(spec, tool_input, result if isinstance(result, dict) else {})
    if not rid:
        return None
    action = 'create' if create_spec is not None else 'delete'
    _sleep = sleep or time.sleep

    elapsed = 0.0
    last_state = 'unknown'
    for delay in backoff:
        if delay:
            _sleep(delay)
            elapsed += delay
        try:
            read = call_tool(spec.read_tool, **spec.read_kwargs(rid, tool_input))
        except Exception as e:  # noqa: BLE001 - a failed read is just "not yet"
            read = {'success': False, 'error': str(e)}

        if action == 'create':
            if _confirms_create(read, rid):
                return {'status': 'confirmed', 'action': 'create', 'resource_id': rid,
                        'via': spec.read_tool, 'after_seconds': elapsed}
        else:
            last_state = delete_spec.gone(read, rid)
            if last_state == 'gone':
                return {'status': 'confirmed', 'action': 'delete', 'resource_id': rid,
                        'via': spec.read_tool, 'after_seconds': elapsed}

    if action == 'create':
        return {
            'status': 'unconfirmed', 'action': 'create', 'resource_id': rid,
            'via': spec.read_tool,
            'message': (
                f"Create returned ID {rid}, but I cannot confirm it via a read yet "
                f"— it may still be propagating. Please check the console."
            ),
        }

    if last_state == 'present':
        msg = (f"Delete of {rid} returned success, but a read still shows it — it may "
               f"still be shutting down. Re-check in a minute or confirm in the console.")
    else:  # 'unknown' — the read kept failing for a non-NotFound reason
        msg = (f"{rid} was deleted (the delete call returned success), but I could not "
               f"verify removal — the read-back is failing. Confirm in the console.")
    return {'status': 'unconfirmed', 'action': 'delete', 'resource_id': rid,
            'via': spec.read_tool, 'message': msg}
