"""Per-process 60s TTL cache for read-only tool results
(Execution Integrity rule 5 — see docs/execution-integrity.md).

"Never re-call describe/list for data already fetched this session." A
reasoning model working a multi-step task routinely calls ``get_ec2_instances``
/ ``list_s3_buckets`` several times in one turn (and across turns of the same
conversation). Each call is a real round-trip to the user's cloud account; the
answer does not change second to second.

Contract:
- Only **read** tools are cached (``is_read_tool``) and only **successful**
  results (``{'success': True}`` or a dict with no ``success`` key).
- Keyed by ``(user_id, tool_name, canonical_args)`` — never served across users.
- 60s TTL. Bounded (``_MAX_ENTRIES``); oldest evicted on overflow.
- **Any mutating tool call for a user drops that user's whole read cache**
  (``invalidate_user``) — a stale read that contradicts a just-applied change
  is worse than a slow one (it's exactly what the Phase 2 verifier guards
  against). Coarse on purpose: mutations are rare, reads are not.
- Thread-safe (gthread workers share the process).
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, Tuple

TTL_SECONDS = 60.0
_MAX_ENTRIES = 512

_READ_PREFIXES = ('get_', 'list_', 'describe_')
# Read tools whose name doesn't start with a read prefix.
_READ_EXTRA = frozenset({'find_ami', 'search_tools'})
# Substrings that mark a generic read escape hatch (aws_api_read, gcp_api_read…).
_READ_SUBSTRINGS = ('_api_read',)
# Never cache these even though the name looks read-y (live/secret/volatile).
_READ_DENY = frozenset({
    'get_secret_value', 'get_iam_credential_report', 'generate_s3_presigned_url',
    'get_ec2_console_output', 'get_s3_object_metadata',
    # Reachability probes must run live every time — a cached "reachable: false"
    # from 60s ago would misreport a service that has since come up (or vice versa).
    'http_check', 'tcp_check', 'run_smoke_test',
})


def is_read_tool(tool_name: str) -> bool:
    name = (tool_name or '').lower()
    if name in _READ_DENY:
        return False
    if name in _READ_EXTRA:
        return True
    if any(s in name for s in _READ_SUBSTRINGS):
        return True
    return name.startswith(_READ_PREFIXES)


def _is_cacheable_result(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    return result.get('success', True) is True


class _ReadCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key -> (result, expires_at)
        self._store: Dict[Tuple[Any, str], Tuple[Any, float]] = {}

    @staticmethod
    def _key(user_id: Any, cache_key: str) -> Tuple[Any, str]:
        return (user_id, cache_key)

    def get(self, user_id: Any, cache_key: str) -> Optional[Any]:
        now = time.monotonic()
        k = self._key(user_id, cache_key)
        with self._lock:
            entry = self._store.get(k)
            if entry is None:
                return None
            result, expires_at = entry
            if expires_at <= now:
                self._store.pop(k, None)
                return None
            return result

    def put(self, user_id: Any, cache_key: str, result: Any) -> None:
        if not _is_cacheable_result(result):
            return
        now = time.monotonic()
        k = self._key(user_id, cache_key)
        with self._lock:
            self._store[k] = (result, now + TTL_SECONDS)
            if len(self._store) > _MAX_ENTRIES:
                self._evict_locked(now)

    def invalidate_user(self, user_id: Any) -> int:
        with self._lock:
            doomed = [k for k in self._store if k[0] == user_id]
            for k in doomed:
                self._store.pop(k, None)
            return len(doomed)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def _evict_locked(self, now: float) -> None:
        # drop expired first
        for k in [k for k, (_r, exp) in self._store.items() if exp <= now]:
            self._store.pop(k, None)
        # then oldest-expiry until under the cap
        if len(self._store) > _MAX_ENTRIES:
            for k, _v in sorted(self._store.items(), key=lambda kv: kv[1][1])[
                    : len(self._store) - _MAX_ENTRIES]:
                self._store.pop(k, None)


# Process-wide singleton.
READ_CACHE = _ReadCache()
