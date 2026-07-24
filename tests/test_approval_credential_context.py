"""Regression: approving a high-risk tool call must run it under the
requester's cloud credential context.

`approval_service._execute_tool` used to call `agent.tools[tool_name](**...)`
directly with no call to `agent._set_cloud_user_context(req.requester_id)` —
unlike `process_message_isolated`/`process_message_streaming`, which always set
it before running a tool (see src/agent/core.py). Since
`aws_tools._get_boto_client` hard-requires a user context to look up per-user
credentials, an approved AWS action either failed closed with "Authentication
required" (silently no-opping a safety-critical action the requester thought
had run) or, worse, could pick up whatever context a previous request left on
this greenlet's thread-local and execute against the wrong user's account.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.approval_service import _execute_tool


def _fake_req(tool_name='some_tool', tool_input=None, requester_id=99):
    return SimpleNamespace(tool_name=tool_name, tool_input=tool_input or {}, requester_id=requester_id)


def test_execute_tool_sets_requester_context_before_running_and_clears_after():
    fake_agent = MagicMock()
    call_order = []
    fake_agent._set_cloud_user_context.side_effect = lambda uid: call_order.append(('set', uid))
    fake_agent._clear_cloud_user_context.side_effect = lambda: call_order.append(('clear',))

    def _tool(**kwargs):
        call_order.append(('run',))
        return {'success': True}

    fake_agent.tools = {'some_tool': _tool}

    with patch('app.agent', fake_agent):
        result = _execute_tool(_fake_req(requester_id=42))

    assert result == {'success': True}
    fake_agent._set_cloud_user_context.assert_called_once_with(42)
    fake_agent._clear_cloud_user_context.assert_called_once()
    # Context must be set before the tool runs and cleared after it.
    assert call_order == [('set', 42), ('run',), ('clear',)]


def test_execute_tool_clears_context_even_if_tool_raises():
    fake_agent = MagicMock()

    def _boom(**kwargs):
        raise RuntimeError('tool blew up')

    fake_agent.tools = {'some_tool': _boom}

    with patch('app.agent', fake_agent):
        result = _execute_tool(_fake_req(requester_id=7))

    assert result['success'] is False
    fake_agent._set_cloud_user_context.assert_called_once_with(7)
    fake_agent._clear_cloud_user_context.assert_called_once()


def test_execute_tool_unknown_tool_never_sets_context():
    fake_agent = MagicMock()
    fake_agent.tools = {}

    with patch('app.agent', fake_agent):
        result = _execute_tool(_fake_req(tool_name='does_not_exist', requester_id=1))

    assert result == {'success': False, 'error': 'Unknown tool: does_not_exist'}
    fake_agent._set_cloud_user_context.assert_not_called()
