"""Synchronous read-back verification for create / delete / update tools
(Execution Integrity rule 2 — see docs/execution-integrity.md).

The agent must never report a mutation as done on the strength of the call's
own response — cloud reads lag writes, and a fabricated-looking success is
indistinguishable from a real one. After a create/delete/update tool returns
success, ``verify_mutation`` calls the resource's dedicated *read* tool a few
times with a short backoff and annotates the result:

  {'_verification': {'status': 'confirmed',   'action': 'create'|'delete'|'update', 'resource_id', 'via', ...}}
  {'_verification': {'status': 'unconfirmed', 'action': 'create'|'delete'|'update', 'resource_id', 'via', 'message'}}

``status == 'unconfirmed'`` is NOT "the operation failed":
  - create: the read hasn't caught up
  - delete: the read still shows the resource (usually mid-shutdown), or the
    read itself is failing
  - update: the read doesn't show the new value yet, or the read is failing
The ``message`` tells the model exactly what to say.

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
# (0), then 1 → 2 → 5 → 7 — ~15s total wall time, 5 attempts. Creates and
# updates propagate fast, so this is deliberately not the full 60s.
DEFAULT_BACKOFF = (0, 1, 2, 5, 7)

# Deletes take longer to reach a terminal state (an EC2 instance sits in
# `shutting-down` for a while) and rule 3 wants TWO consecutive confirming
# reads — so deletes get the full ~57s chain.
DELETE_BACKOFF = (0, 2, 5, 10, 20, 20)

# Rule 3: a terminate/delete is only "confirmed" after this many consecutive
# live reads agree the resource is gone / in a terminal state.
DELETE_CONFIRMING_READS = 2

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


class _UpdateSpec:
    __slots__ = ('read_tool', 'id_prefix', 'input_key', 'read_kwargs', 'find',
                 'expected', 'accepted_states', 'applies')

    def __init__(self, read_tool, *, expected, id_prefix=None, input_key=None,
                 read_kwargs=None, find=None, accepted_states=(), applies=None):
        self.read_tool = read_tool
        # expected: (tool_input) -> {read_field: target_value} for the params the
        # caller actually passed. Empty dict => nothing checkable => 'unknown'.
        self.expected = expected
        # find: (read_result, rid) -> the sub-dict for this resource, for
        # list-style reads. None => the read result itself is the object.
        self.find = find
        # A read whose 'status'/'state' is in accepted_states counts as applied
        # even before the target value shows (e.g. RDS 'modifying').
        self.accepted_states = set(accepted_states)
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

# ---- update specs: confirm the new value is LIVE --------------------------

def _find_ec2(read, rid):
    for inst in (read.get('instances') or []) if isinstance(read, dict) else []:
        if isinstance(inst, dict) and inst.get('instance_id') == rid:
            return inst
    return None


def _find_by(key):
    def _f(read, rid):
        for item in _iter_records(read):
            if str(item.get(key)) == str(rid):
                return item
        return None
    return _f


def _iter_records(read):
    if not isinstance(read, dict):
        return
    for v in read.values():
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    yield item


_EC2_STATE_TARGET = {'start': 'running', 'stop': 'stopped', 'reboot': 'running'}

_UPDATE_SPECS: Dict[str, _UpdateSpec] = {
    'resize_ec2_instance': _UpdateSpec(
        'get_ec2_instances', input_key='instance_id', find=_find_ec2,
        read_kwargs=lambda rid, ti: {'filters': {'instance-id': rid}},
        expected=lambda ti: {'instance_type': ti['new_instance_type']}
        if ti.get('new_instance_type') else {}),
    'manage_ec2_instance': _UpdateSpec(
        'get_ec2_instances', input_key='instance_id', find=_find_ec2,
        read_kwargs=lambda rid, ti: {'filters': {'instance-id': rid}},
        applies=lambda ti: str(ti.get('action', '')).lower() in _EC2_STATE_TARGET,
        expected=lambda ti: {'state': _EC2_STATE_TARGET[str(ti['action']).lower()]}),
    'update_ecs_service': _UpdateSpec(
        'list_ecs_services', input_key='service', find=_find_by('service_name'),
        read_kwargs=lambda rid, ti: {'cluster': ti.get('cluster')},
        expected=lambda ti: {'desired_count': ti['desired_count']}
        if ti.get('desired_count') is not None else {}),
    'update_lambda_function_config': _UpdateSpec(
        'list_lambda_functions', input_key='function_name',
        find=_find_by('function_name'),
        read_kwargs=lambda rid, ti: {},
        expected=lambda ti: {k: ti[k] for k in ('memory_size', 'timeout', 'runtime')
                             if ti.get(k) is not None}),
    'modify_rds_instance': _UpdateSpec(
        'describe_rds_instance', input_key='db_instance_identifier',
        read_kwargs=lambda rid, ti: {'db_instance_identifier': rid},
        accepted_states=('modifying',),
        expected=lambda ti: {k: ti[v] for k, v in (
            ('db_instance_class', 'db_instance_class'),
            ('engine_version', 'engine_version')) if ti.get(v)}),
}


def _update_state(spec: _UpdateSpec, read: Any, rid: str, tool_input: dict) -> str:
    """'applied' | 'not_yet' | 'unknown' for one read-back of an update."""
    if not isinstance(read, dict) or read.get('success') is not True:
        return 'unknown'
    obj = spec.find(read, rid) if spec.find else read
    if not isinstance(obj, dict):
        return 'unknown'
    exp = spec.expected(tool_input)
    if not exp:
        return 'unknown'                       # nothing checkable
    state = str(obj.get('status') or obj.get('state') or '').lower()
    if spec.accepted_states and state in spec.accepted_states:
        return 'applied'
    return 'applied' if all(str(obj.get(k)) == str(v) for k, v in exp.items()) else 'not_yet'


_RESOURCE_ID_KEYS = {
    'instanceid', 'instance_id', 'groupid', 'group_id', 'security_group_id',
    'vpcid', 'vpc_id', 'db_instance_identifier', 'dbinstanceidentifier',
    'bucketname', 'bucket_name', 'id', 'arn',
}


def is_verifiable(tool_name: str) -> bool:
    return (tool_name in _CREATE_SPECS or tool_name in _DELETE_SPECS
            or tool_name in _UPDATE_SPECS)


def will_verify(tool_name: str, tool_input: dict) -> bool:
    """Like ``is_verifiable`` but also honours a spec's ``applies`` predicate
    (e.g. ``manage_ec2_instance`` verifies ``action='terminate'`` as a delete
    and ``start``/``stop``/``reboot`` as an update, but never ``describe``) —
    so the caller only spends a per-turn verification slot when a read-back
    will actually run."""
    action, _spec = _pick_spec(tool_name, tool_input or {})
    return action is not None


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


def _pick_spec(tool_name: str, tool_input: dict):
    """(action, spec) for this call, or (None, None) — honouring ``applies``."""
    if tool_name in _CREATE_SPECS:
        return 'create', _CREATE_SPECS[tool_name]
    dspec = _DELETE_SPECS.get(tool_name)
    if dspec is not None and dspec.applies(tool_input):
        return 'delete', dspec
    uspec = _UPDATE_SPECS.get(tool_name)
    if uspec is not None and uspec.applies(tool_input):
        return 'update', uspec
    return None, None


def _poll(spec, rid, tool_input, call_tool, sleep, backoff, decide):
    """Run the read-back loop. ``decide(read) -> (verdict, done)``; returns
    ``(final_verdict, elapsed_seconds, reads)`` where ``reads`` is the verdict
    from every attempt (for the rule-10 audit trail)."""
    elapsed = 0.0
    verdict = 'unknown'
    reads = []
    for delay in backoff:
        if delay:
            sleep(delay)
            elapsed += delay
        try:
            read = call_tool(spec.read_tool, **spec.read_kwargs(rid, tool_input))
        except Exception as e:  # noqa: BLE001 - a failed read is just "not yet"
            read = {'success': False, 'error': str(e)}
        verdict, done = decide(read)
        reads.append(verdict)
        if done:
            break
    return verdict, elapsed, reads


def verify_mutation(
    tool_name: str,
    tool_input: dict,
    result: dict,
    *,
    call_tool: Callable[..., dict],
    sleep: Optional[Callable[[float], None]] = None,
    backoff: tuple = DEFAULT_BACKOFF,
) -> Optional[Dict[str, Any]]:
    """Read-back-verify a successful create / delete / update tool result.

    Returns an annotation dict for ``result['_verification']`` or ``None`` when
    the tool is not verifiable / not applicable / no resource id resolvable.
    Never raises — a read that errors just counts as "not confirmed yet".
    """
    tool_input = tool_input or {}
    action, spec = _pick_spec(tool_name, tool_input)
    if spec is None:
        return None
    rid = _resolve_id(spec, tool_input, result if isinstance(result, dict) else {})
    if not rid:
        return None
    _sleep = sleep or time.sleep
    base = {'action': action, 'resource_id': rid, 'via': spec.read_tool}

    if action == 'create':
        verdict, elapsed, _reads = _poll(
            spec, rid, tool_input, call_tool, _sleep, backoff,
            lambda read: ('confirmed', True) if _confirms_create(read, rid) else ('unconfirmed', False))
        if verdict == 'confirmed':
            return {**base, 'status': 'confirmed', 'after_seconds': elapsed}
        return {**base, 'status': 'unconfirmed', 'message': (
            f"Create returned ID {rid}, but I cannot confirm it via a read yet "
            f"— it may still be propagating. Please check the console.")}

    if action == 'delete':
        # Rule 3: only "confirmed" after DELETE_CONFIRMING_READS consecutive
        # `gone` reads; a `present`/`unknown` read resets the streak.
        streak = {'n': 0}

        def _delete_decide(read):
            s = spec.gone(read, rid)
            streak['n'] = streak['n'] + 1 if s == 'gone' else 0
            return s, streak['n'] >= DELETE_CONFIRMING_READS

        verdict, elapsed, reads = _poll(
            spec, rid, tool_input, call_tool, _sleep, DELETE_BACKOFF, _delete_decide)
        confirmed = streak['n'] >= DELETE_CONFIRMING_READS
        ann = {**base, 'reads': reads, 'confirming_reads': DELETE_CONFIRMING_READS,
               'after_seconds': elapsed}
        if confirmed:
            return {**ann, 'status': 'confirmed'}
        if verdict == 'present' or 'present' in reads:
            ann['message'] = (
                f"Delete of {rid} returned success, but a read still shows it — the "
                f"terminate may not have taken. Re-issue the terminate for {rid} and "
                f"I will re-verify. Do not tell the user it is gone yet.")
        else:
            ann['message'] = (
                f"{rid} was deleted (the delete call returned success), but I could not "
                f"get two consecutive reads confirming removal — the read-back is "
                f"failing. Re-issue the terminate for {rid}, or confirm in the console.")
        return {**ann, 'status': 'unconfirmed'}

    # update
    fields = sorted(spec.expected(tool_input))
    verdict, elapsed, _reads = _poll(
        spec, rid, tool_input, call_tool, _sleep, backoff,
        lambda read: (lambda s: (s, s == 'applied'))(_update_state(spec, read, rid, tool_input)))
    if verdict == 'applied':
        return {**base, 'status': 'confirmed', 'fields': fields, 'after_seconds': elapsed}
    if verdict == 'not_yet':
        msg = (f"Update of {rid} returned success, but a read does not yet show the new "
               f"value for {', '.join(fields) or 'the changed setting'}. The change may "
               f"still be applying — re-check or confirm in the console.")
    else:
        msg = (f"{rid} was updated (the call returned success), but I could not verify "
               f"the new value — the read-back is failing. Confirm in the console.")
    return {**base, 'status': 'unconfirmed', 'fields': fields, 'message': msg}
