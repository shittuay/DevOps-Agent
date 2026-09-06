"""Synchronous read-back verification for creating tools (Execution Integrity
rule 2 — see docs/execution-integrity.md).

The agent must never report a create as done on the strength of the create
call's own response — cloud reads lag writes, and a fabricated-looking success
is indistinguishable from a real one. After a creating tool returns success,
``verify_mutation`` calls the resource's dedicated *read* tool a few times with
a short backoff and annotates the result:

  {'_verification': {'status': 'confirmed',   'resource_id': ..., 'via': ...}}
  {'_verification': {'status': 'unconfirmed', 'resource_id': ..., 'message': ...}}

``status == 'unconfirmed'`` is NOT "the create failed" — it means the read
hasn't caught up. The message tells the model exactly what to say.

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

# Max creating tools verified per turn — a turn that launches 10 instances
# should not add 150s. The rest are recorded in the registry unverified.
MAX_VERIFICATIONS_PER_TURN = 3


class _Spec:
    __slots__ = ('read_tool', 'id_prefix', 'input_key', 'read_kwargs')

    def __init__(self, read_tool: str, *, id_prefix: Optional[str] = None,
                 input_key: Optional[str] = None,
                 read_kwargs: Callable[[str, dict], dict] = None):
        self.read_tool = read_tool
        self.id_prefix = id_prefix
        self.input_key = input_key
        self.read_kwargs = read_kwargs or (lambda rid, ti: {})


# Creating tool -> how to confirm the resource exists.
_SPECS: Dict[str, _Spec] = {
    'create_ec2_instance': _Spec(
        'get_ec2_instances', id_prefix='i-',
        read_kwargs=lambda rid, ti: {'filters': {'instance-id': rid}},
    ),
    'run_instances': _Spec(
        'get_ec2_instances', id_prefix='i-',
        read_kwargs=lambda rid, ti: {'filters': {'instance-id': rid}},
    ),
    'create_security_group': _Spec(
        'describe_security_group', id_prefix='sg-',
        read_kwargs=lambda rid, ti: {'group_id': rid},
    ),
    'create_vpc': _Spec(
        'describe_vpc', id_prefix='vpc-',
        read_kwargs=lambda rid, ti: {'vpc_id': rid},
    ),
    'create_rds_instance': _Spec(
        'describe_rds_instance', input_key='db_instance_identifier',
        read_kwargs=lambda rid, ti: {'db_instance_identifier': rid},
    ),
    'create_s3_bucket': _Spec(
        'get_s3_bucket_info', input_key='bucket_name',
        read_kwargs=lambda rid, ti: {'bucket_name': rid},
    ),
}

_RESOURCE_ID_KEYS = {
    'instanceid', 'instance_id', 'groupid', 'group_id', 'security_group_id',
    'vpcid', 'vpc_id', 'db_instance_identifier', 'dbinstanceidentifier',
    'bucketname', 'bucket_name', 'id', 'arn',
}


def is_verifiable(tool_name: str) -> bool:
    return tool_name in _SPECS


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


def _resolve_id(spec: _Spec, tool_input: dict, result: dict) -> Optional[str]:
    """The resource id to read back — from the result (preferred) or the input."""
    if spec.id_prefix:
        for _key, val in _walk_strings(result):
            if val.startswith(spec.id_prefix) and _AWS_ID_RE.match(val):
                return val
    if spec.input_key and tool_input.get(spec.input_key):
        return str(tool_input[spec.input_key])
    if spec.input_key:
        # sometimes the create echoes the name back in the result
        for key, val in _walk_strings(result):
            if key in _RESOURCE_ID_KEYS and val:
                return val
    return None


def _confirms(read_result: Any, resource_id: str) -> bool:
    """The read confirms the resource iff it succeeded AND names the id back.

    Every read tool in ``_SPECS`` echoes the queried id in its success payload
    (``get_ec2_instances`` returns the instance, the ``describe_*`` tools echo
    ``group_id`` / ``vpc_id`` / ``db_instance_identifier``, ``get_s3_bucket_info``
    echoes ``bucket_name``), so requiring the echo also guards against a read
    that returns success with an empty/unrelated body.
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
    """Read-back-verify a successful creating-tool result.

    Returns an annotation dict for ``result['_verification']`` or ``None`` when
    the tool is not verifiable / no resource id could be resolved. Never raises
    — a read that errors just counts as "not confirmed yet".
    """
    spec = _SPECS.get(tool_name)
    if spec is None:
        return None
    rid = _resolve_id(spec, tool_input or {}, result if isinstance(result, dict) else {})
    if not rid:
        return None

    _sleep = sleep or time.sleep
    elapsed = 0.0
    for delay in backoff:
        if delay:
            _sleep(delay)
            elapsed += delay
        try:
            read = call_tool(spec.read_tool, **spec.read_kwargs(rid, tool_input or {}))
        except Exception as e:  # noqa: BLE001 - a failed read is just "not yet"
            read = {'success': False, 'error': str(e)}
        if _confirms(read, rid):
            return {
                'status': 'confirmed',
                'resource_id': rid,
                'via': spec.read_tool,
                'after_seconds': elapsed,
            }

    return {
        'status': 'unconfirmed',
        'resource_id': rid,
        'via': spec.read_tool,
        'message': (
            f"Create returned ID {rid}, but I cannot confirm it via a read yet "
            f"— it may still be propagating. Please check the console."
        ),
    }
