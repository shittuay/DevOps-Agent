"""Regression: DevOpsAgent._clear_cloud_user_context() must clear every
provider's thread-local user context, not just AWS/Azure/GCP.

`src/tools/devops_operations_tools.py` (cost analysis, change governance,
compliance tools) has its own thread-local `_user_context`, set via
`set_user_context()` from `DevOpsAgent._set_cloud_user_context()` alongside
the AWS/Azure/GCP setters. Unlike its siblings, the module never defined a
`clear_user_context()`, and `_clear_cloud_user_context()` had no call for it
at all -- the set side was even wrapped in a bare
`except (ImportError, Exception): pass` that silently swallowed failures
with no logging, unlike every other provider block in the same function.

Net effect: after a request finished, the devops-operations user context
stayed set to that request's user_id indefinitely on that thread until the
next explicit `set_user_context()` call overwrote it -- e.g.
`services/approval_service.py`'s `_execute_tool()` sets it for the
requester, then calls `agent._clear_cloud_user_context()` in a `finally`
expecting a clean slate, but the devops context was never actually reset.
Any later code on that thread that reads `get_current_user_id()` before
setting its own context could pick up a stale user's id for cost/compliance/
change-governance queries.
"""
from unittest.mock import MagicMock

from src.agent.core import DevOpsAgent
from src.tools import devops_operations_tools


def _fake_self():
    fake = MagicMock()
    fake.logger = MagicMock()
    return fake


def test_set_cloud_user_context_sets_devops_context():
    devops_operations_tools.clear_user_context()
    try:
        DevOpsAgent._set_cloud_user_context(_fake_self(), 55)
        assert devops_operations_tools.get_current_user_id() == 55
    finally:
        devops_operations_tools.clear_user_context()


def test_clear_cloud_user_context_clears_devops_context():
    devops_operations_tools.set_user_context(55)
    try:
        DevOpsAgent._clear_cloud_user_context(_fake_self())
        assert devops_operations_tools.get_current_user_id() is None
    finally:
        devops_operations_tools.clear_user_context()


def test_devops_operations_tools_clear_user_context_resets_to_none():
    devops_operations_tools.set_user_context(7)
    assert devops_operations_tools.get_current_user_id() == 7
    devops_operations_tools.clear_user_context()
    assert devops_operations_tools.get_current_user_id() is None
