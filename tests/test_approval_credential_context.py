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


def _fake_req(tool_name='some_tool', tool_input=None, requester_id=99, conversation_id=None):
    return SimpleNamespace(
        tool_name=tool_name, tool_input=tool_input or {}, requester_id=requester_id,
        conversation_id=conversation_id,
    )


def _passthrough_agent():
    """A MagicMock agent whose _verify_and_annotate behaves like the real one
    when nothing is verifiable: return the result unchanged."""
    fake_agent = MagicMock()
    fake_agent._verify_and_annotate.side_effect = lambda name, ti, result: result
    return fake_agent


def test_execute_tool_sets_requester_context_before_running_and_clears_after():
    fake_agent = _passthrough_agent()
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
    fake_agent = _passthrough_agent()

    def _boom(**kwargs):
        raise RuntimeError('tool blew up')

    fake_agent.tools = {'some_tool': _boom}

    with patch('app.agent', fake_agent):
        result = _execute_tool(_fake_req(requester_id=7))

    assert result['success'] is False
    fake_agent._set_cloud_user_context.assert_called_once_with(7)
    fake_agent._clear_cloud_user_context.assert_called_once()
    # A raised tool is recorded, but never audited/verified as a success.
    fake_agent._record_tool_call.assert_called_once_with('some_tool', result, outcome='raised')
    fake_agent._audit_infrastructure_change.assert_not_called()
    fake_agent._verify_and_annotate.assert_not_called()


def test_execute_tool_unknown_tool_never_sets_context():
    fake_agent = _passthrough_agent()
    fake_agent.tools = {}

    with patch('app.agent', fake_agent):
        result = _execute_tool(_fake_req(tool_name='does_not_exist', requester_id=1))

    assert result == {'success': False, 'error': 'Unknown tool: does_not_exist'}
    fake_agent._set_cloud_user_context.assert_not_called()


def test_execute_tool_audits_records_and_verifies_like_every_other_execution_site():
    """Regression: `_execute_tool` used to call `agent.tools[tool_name](**...)`
    with none of the three instrumentation calls every other tool-execution site
    in src/agent/core.py makes — so an approved delete/terminate left no
    InfrastructureChange audit row, no usage_logs signal, and no Execution
    Integrity read-back verification, unlike the identical tool run from a
    same-turn self-confirmation.
    """
    fake_agent = _passthrough_agent()
    call_order = []
    fake_agent._set_cloud_user_context.side_effect = lambda uid: call_order.append('set_ctx')
    fake_agent._reset_turn_tool_state.side_effect = lambda: call_order.append('reset')
    fake_agent._audit_infrastructure_change.side_effect = lambda *a: call_order.append('audit')
    fake_agent._record_tool_call.side_effect = lambda *a, **k: call_order.append('record')
    fake_agent._verify_and_annotate.side_effect = lambda name, ti, result: (call_order.append('verify'), result)[1]
    fake_agent._clear_cloud_user_context.side_effect = lambda: call_order.append('clear_ctx')

    def _tool(**kwargs):
        call_order.append('run')
        return {'success': True, 'instance_id': 'i-0abc123def456789'}

    fake_agent.tools = {'delete_ec2_instance': _tool}

    with patch('app.agent', fake_agent):
        result = _execute_tool(_fake_req(
            tool_name='delete_ec2_instance',
            tool_input={'instance_id': 'i-0abc123def456789'},
            requester_id=42,
        ))

    assert result == {'success': True, 'instance_id': 'i-0abc123def456789'}
    fake_agent._audit_infrastructure_change.assert_called_once_with(
        'delete_ec2_instance', {'instance_id': 'i-0abc123def456789'}, result)
    fake_agent._record_tool_call.assert_called_once_with(
        'delete_ec2_instance', result, outcome='ran')
    fake_agent._verify_and_annotate.assert_called_once_with(
        'delete_ec2_instance', {'instance_id': 'i-0abc123def456789'}, result)
    # Order matches core.py's model-loop sites: reset per-turn state, set the
    # credential context, run the tool, then record -> verify -> audit (audit
    # last so it can read result['_verification']), then clear.
    assert call_order == ['reset', 'set_ctx', 'run', 'record', 'verify', 'audit', 'clear_ctx']
    # requester_id must be visible on the agent as the current-user context so
    # _audit_infrastructure_change (which reads self._current_user_id) attributes
    # the change correctly, and it must not leak past this call.
    assert fake_agent._current_user_id is None
    assert fake_agent._current_conversation_id is None
