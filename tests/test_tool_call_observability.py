"""Tool-call observability: a guessed / not-offered tool, or a tool that
returns ``{'success': False}``, must leave a consistent, queryable trace on
every provider path.

Background — CLAUDE_RUNBOOK.md, 2026-09-02:
  - ``_last_tools_used`` was appended differently at each of the five executor
    sites (Kimi non-streaming, Kimi streaming, Claude), so a tool the model
    guessed that selection never offered left *no* row in ``usage_logs`` on the
    Kimi non-streaming tier — the unexplained ``create_ec2_keypair`` with no
    ``tool_use`` row.
  - ``usage_logs.success`` on a per-tool row was the turn-completion flag, not
    the tool's own result (the false "unwanted RDS instance" alarm).

The fix routes every executor site through ``_record_tool_call`` and exposes
``last_tool_calls`` (name + real per-tool outcome, not deduplicated).
"""
import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _make_agent():
    from src.agent.core import DevOpsAgent
    cfg = MagicMock()
    cfg.get.return_value = None
    cfg.claude_model = 'claude-sonnet-4-6'
    cfg.claude_max_tokens = 4096
    cfg.claude_temperature = 0.0
    with patch('src.agent.core.anthropic.Anthropic'):
        agent = DevOpsAgent(cfg)
    agent.register_tool(
        name='list_ec2_instances', description='List EC2 instances',
        input_schema={'type': 'object', 'properties': {}},
        handler=lambda **kw: {'success': True, 'instances': []},
    )
    agent.register_tool(
        name='create_ec2_instance', description='Create an EC2 instance',
        input_schema={'type': 'object', 'properties': {}},
        handler=lambda **kw: {'success': False, 'error': 'ami_id is required — call find_ami first'},
    )
    agent.register_tool(
        name='boom', description='Always raises',
        input_schema={'type': 'object', 'properties': {}},
        handler=lambda **kw: (_ for _ in ()).throw(RuntimeError('kaboom')),
    )
    return agent


# --------------------------------------------------------------------------
# _not_offered_result — the structured warning
# --------------------------------------------------------------------------

class TestNotOfferedWarning:
    def test_withheld_tool_logs_tool_not_offered(self, caplog):
        agent = _make_agent()
        agent.register_tool('list_iam_roles', 'List IAM roles', {}, lambda **kw: {'success': True})
        agent._tools_override = [{'name': 'list_ec2_instances', 'description': '', 'input_schema': {}}]

        with caplog.at_level(logging.WARNING):
            result = agent._not_offered_result('list_iam_roles')

        assert result['success'] is False
        assert 'search_tools' in result['error']
        rec = [r for r in caplog.records if 'tool-not-offered' in r.getMessage()]
        assert rec, "expected a 'tool-not-offered' warning"
        assert 'list_iam_roles' in rec[0].getMessage()
        assert 'withheld' in rec[0].getMessage()

    def test_unknown_tool_logs_no_such_tool(self, caplog):
        agent = _make_agent()
        agent._tools_override = [{'name': 'list_ec2_instances', 'description': '', 'input_schema': {}}]

        with caplog.at_level(logging.WARNING):
            agent._not_offered_result('totally_made_up_tool')

        rec = [r for r in caplog.records if 'tool-not-offered' in r.getMessage()]
        assert rec and 'no such tool' in rec[0].getMessage()


# --------------------------------------------------------------------------
# _record_tool_call — the structured per-call log
# --------------------------------------------------------------------------

class TestRecordToolCall:
    def test_ran_ok(self):
        agent = _make_agent()
        agent._record_tool_call('list_ec2_instances', {'success': True}, outcome='ran')
        assert agent._last_tools_used == ['list_ec2_instances']
        assert agent.last_tool_calls == [
            {'tool': 'list_ec2_instances', 'status': 'ok', 'success': True, 'error': None}
        ]

    def test_ran_but_result_failed(self):
        agent = _make_agent()
        agent._record_tool_call('create_ec2_instance', {'success': False, 'error': 'nope'}, outcome='ran')
        # still "ran", so it counts as used, but the outcome is an error
        assert agent._last_tools_used == ['create_ec2_instance']
        entry = agent.last_tool_calls[0]
        assert entry['status'] == 'error' and entry['success'] is False and entry['error'] == 'nope'

    def test_raised(self):
        agent = _make_agent()
        agent._record_tool_call('boom', {'success': False, 'error': 'boom'}, outcome='raised')
        assert agent.last_tool_calls[0]['status'] == 'error'
        assert agent.last_tool_calls[0]['success'] is False

    def test_not_offered_is_not_counted_as_used(self):
        agent = _make_agent()
        agent._record_tool_call('list_iam_roles', {'success': False}, outcome='not_offered')
        assert agent._last_tools_used == []          # not "used"
        assert agent.last_tool_calls[0]['status'] == 'not_offered'
        assert agent.last_tool_calls[0]['success'] is False

    def test_error_is_truncated(self):
        agent = _make_agent()
        agent._record_tool_call('x', {'success': False, 'error': 'e' * 999}, outcome='ran')
        assert len(agent.last_tool_calls[0]['error']) == 250


# --------------------------------------------------------------------------
# End to end: the Kimi non-streaming tool loop
# --------------------------------------------------------------------------

def _tool_then_text(tool_name, tool_args, final_text='done'):
    """Two responses: one tool call, then a plain-text completion."""
    calls = {'n': 0}

    def fake_create(**params):
        calls['n'] += 1
        if calls['n'] == 1:
            tc = SimpleNamespace(id='c1', function=SimpleNamespace(
                name=tool_name, arguments=json.dumps(tool_args)))
            msg = MagicMock()
            msg.tool_calls = [tc]
            msg.content = ''
            msg.reasoning_content = None
            msg.model_dump.return_value = {'role': 'assistant', 'content': '', 'tool_calls': []}
            return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason='tool_calls')], usage=None)
        msg = SimpleNamespace(tool_calls=None, content=final_text, reasoning_content=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason='stop')], usage=None)

    return fake_create


@pytest.fixture
def kimi_env(monkeypatch):
    monkeypatch.setenv('MOONSHOT_API_KEY', 'test-key')


def _run_kimi(agent, fake_create):
    from src.agent.conversation import ConversationManager
    agent.conversation = ConversationManager()
    agent.conversation.add_user_message('do the thing')
    agent._last_tools_used = []
    agent._tool_call_log = []
    client = MagicMock()
    client.chat.completions.create.side_effect = fake_create
    with patch('openai.OpenAI', return_value=client):
        return agent._call_kimi_api()


def test_kimi_records_a_guessed_not_offered_tool(kimi_env):
    agent = _make_agent()
    # selection offered only list_ec2_instances; the model guesses list_iam_roles
    agent.register_tool('list_iam_roles', 'List IAM roles', {}, lambda **kw: {'success': True})
    agent._tools_override = [
        td for td in agent.tool_definitions if td['name'] in ('list_ec2_instances', 'search_tools')
    ]

    _run_kimi(agent, _tool_then_text('list_iam_roles', {}))

    # It never ran ...
    assert 'list_iam_roles' not in agent.last_tools_used
    # ... but it is not invisible any more.
    statuses = {c['tool']: c['status'] for c in agent.last_tool_calls}
    assert statuses.get('list_iam_roles') == 'not_offered'


def test_kimi_records_a_failed_tool_result(kimi_env):
    agent = _make_agent()
    agent._tools_override = [
        td for td in agent.tool_definitions if td['name'] in ('create_ec2_instance', 'search_tools')
    ]

    _run_kimi(agent, _tool_then_text('create_ec2_instance', {}))

    entry = [c for c in agent.last_tool_calls if c['tool'] == 'create_ec2_instance'][0]
    assert entry['status'] == 'error'
    assert entry['success'] is False
    assert 'find_ami' in entry['error']
    # the tool *ran*, so it still counts as used for primary-tool attribution
    assert 'create_ec2_instance' in agent.last_tools_used


def test_kimi_records_a_raising_tool(kimi_env):
    agent = _make_agent()
    agent._tools_override = [
        td for td in agent.tool_definitions if td['name'] in ('boom', 'search_tools')
    ]

    _run_kimi(agent, _tool_then_text('boom', {}))

    entry = [c for c in agent.last_tool_calls if c['tool'] == 'boom'][0]
    assert entry['status'] == 'error' and entry['success'] is False


def test_last_tools_used_still_dedups_and_counts_only_runs(kimi_env):
    agent = _make_agent()
    agent._record_tool_call('list_ec2_instances', {'success': True}, outcome='ran')
    agent._record_tool_call('list_ec2_instances', {'success': True}, outcome='ran')
    agent._record_tool_call('list_iam_roles', {'success': False}, outcome='not_offered')
    assert agent.last_tools_used == ['list_ec2_instances']
    assert len(agent.last_tool_calls) == 3


# --------------------------------------------------------------------------
# Sandbox mode must never file a real ApprovalRequest for a high-risk tool.
#
# `validation.requires_confirmation` was checked before `self._sandbox_mode`
# at every tool-execution site (Kimi non-streaming, Kimi streaming, Claude).
# A plain 'user'-role account in Sandbox Mode asking to delete/terminate a
# resource therefore filed a *real* ApprovalRequest, emailed a *real*
# approver/admin with no sandbox marker anywhere on the request, and — if
# approved — ran the tool for real via approval_service._execute_tool. This
# broke Sandbox Mode's core guarantee (CLAUDE.md: "Simulated tool results...
# not a substitute for a missing account") for every confirmation-gated tool.
# --------------------------------------------------------------------------

class TestSandboxNeverFilesRealApproval:
    def _sandbox_agent(self):
        agent = _make_agent()
        agent.register_tool(
            'delete_ec2_instance', 'Terminate an EC2 instance', {},
            lambda **kw: {'success': True, 'real_delete_happened': True},
        )
        agent._sandbox_mode = True
        agent._current_user_id = 1
        return agent

    def _regular_user(self):
        return SimpleNamespace(id=1, role='user')

    def test_kimi_non_streaming_mocks_instead_of_filing_approval(self, kimi_env, app):
        agent = self._sandbox_agent()
        agent._tools_override = [
            td for td in agent.tool_definitions
            if td['name'] in ('delete_ec2_instance', 'search_tools')
        ]

        with patch('models.User.query') as user_query, \
             patch('services.approval_service.create_request') as create_request:
            user_query.get.return_value = self._regular_user()
            _run_kimi(agent, _tool_then_text('delete_ec2_instance', {'instance_id': 'i-abc'}))

        create_request.assert_not_called()
        entry = [c for c in agent.last_tool_calls if c['tool'] == 'delete_ec2_instance'][0]
        assert entry['status'] == 'ok'

    def test_kimi_streaming_mocks_instead_of_filing_approval(self, kimi_env, app):
        agent = self._sandbox_agent()
        agent._tools_override = [
            td for td in agent.tool_definitions
            if td['name'] in ('delete_ec2_instance', 'search_tools')
        ]
        from src.agent.conversation import ConversationManager
        agent.conversation = ConversationManager()
        agent.conversation.add_user_message('delete it')

        client = MagicMock()
        client.chat.completions.create.side_effect = _tool_then_text('delete_ec2_instance', {'instance_id': 'i-abc'})

        with patch('models.User.query') as user_query, \
             patch('services.approval_service.create_request') as create_request, \
             patch('openai.OpenAI', return_value=client):
            user_query.get.return_value = self._regular_user()
            chunks = list(agent._call_kimi_api_streaming())

        create_request.assert_not_called()
        assert not any(
            isinstance(c, str) and c.startswith('\x00APPROVAL_REQUIRED\x00') for c in chunks
        )
