"""Execution Integrity Phase 1 — prompt rules + the cheap guardrail hooks.

Covers:
  - the EXECUTION INTEGRITY block in STABLE_SYSTEM_PROMPT (+ cache invariants)
  - build_volatile_tail's new session_context parameter
  - the session resource registry (_created_resources / _extract_created_resource_ids)
  - _audit_infrastructure_change recording creates as well as deletes
  - guard-note surfacing to the user (repeat guard + repeated not-offered guess)
"""
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
        return DevOpsAgent(cfg)


# --------------------------------------------------------------------------
# 1. system prompt
# --------------------------------------------------------------------------

class TestSystemPrompt:
    def test_execution_integrity_block_present(self):
        from src.agent.core import STABLE_SYSTEM_PROMPT
        assert '=== EXECUTION INTEGRITY ===' in STABLE_SYSTEM_PROMPT
        # the exact phrase the model must emit when it cannot confirm a create
        assert 'I cannot confirm it via a read yet' in STABLE_SYSTEM_PROMPT
        assert 'Console truth beats your inference' in STABLE_SYSTEM_PROMPT

    def test_prompt_cache_structural_invariants_hold(self):
        from src.agent.core import STABLE_SYSTEM_PROMPT
        assert '{preferences}' not in STABLE_SYSTEM_PROMPT
        assert 'User Preferences and Context:' not in STABLE_SYSTEM_PROMPT
        assert not STABLE_SYSTEM_PROMPT.endswith('\n')
        assert len(STABLE_SYSTEM_PROMPT) > 2000


# --------------------------------------------------------------------------
# 2. build_volatile_tail
# --------------------------------------------------------------------------

class TestVolatileTail:
    def test_session_context_appended(self):
        from src.agent.prompt_cache import build_volatile_tail
        out = build_volatile_tail('PREFS', None, session_context='REGISTRY')
        assert out == 'User Preferences and Context:\nPREFS\n\nREGISTRY'

    def test_no_session_context_is_byte_identical_to_before(self):
        from src.agent.prompt_cache import build_volatile_tail
        assert build_volatile_tail('PREFS') == 'User Preferences and Context:\nPREFS'
        assert build_volatile_tail('PREFS', 'TRIAL') == \
            'User Preferences and Context:\nPREFS\n\nTRIAL'
        assert build_volatile_tail(None) == \
            'User Preferences and Context:\nNo specific preferences set.'

    def test_session_context_after_trial(self):
        from src.agent.prompt_cache import build_volatile_tail
        out = build_volatile_tail('P', 'T', session_context='R')
        assert out == 'User Preferences and Context:\nP\n\nT\n\nR'


# --------------------------------------------------------------------------
# 3. session resource registry
# --------------------------------------------------------------------------

class TestResourceRegistry:
    def test_id_extraction_from_nested_create_result(self):
        from src.agent.core import _extract_created_resource_ids
        result = {'success': True, 'instance': {
            'InstanceId': 'i-0abc123def456', 'State': {'Name': 'pending'}}}
        assert 'i-0abc123def456' in _extract_created_resource_ids(result)

    def test_id_extraction_ignores_state_words(self):
        from src.agent.core import _extract_created_resource_ids
        ids = _extract_created_resource_ids({'success': True, 'status': 'running'})
        assert 'running' not in ids

    def test_creating_tool_classification(self):
        from src.agent.core import _is_creating_tool
        assert _is_creating_tool('create_ec2_instance')
        assert _is_creating_tool('run_instances')
        assert _is_creating_tool('launch_ec2_instance')
        assert not _is_creating_tool('list_ec2_instances')
        assert not _is_creating_tool('get_ec2_instances')
        assert not _is_creating_tool('create_change_request')   # governance object
        assert not _is_creating_tool('create_security_group_rule')  # _rule excluded

    def test_record_tool_call_populates_registry_for_a_successful_create(self):
        agent = _make_agent()
        agent._record_tool_call(
            'create_ec2_instance',
            {'success': True, 'instance': {'InstanceId': 'i-0abc123def456'}},
            outcome='ran',
        )
        assert len(agent._created_resources) == 1
        assert agent._created_resources[0]['ids'] == ['i-0abc123def456']
        assert agent._created_resources[0]['tool'] == 'create_ec2_instance'

    def test_registry_skips_reads_and_failed_creates(self):
        agent = _make_agent()
        agent._record_tool_call('get_ec2_instances', {'success': True, 'instances': [
            {'InstanceId': 'i-0aaa'}]}, outcome='ran')
        agent._record_tool_call('create_ec2_instance', {
            'success': False, 'error': 'ami_id required'}, outcome='ran')
        assert agent._created_resources == []

    def test_session_context_empty_without_conversation_id(self):
        agent = _make_agent()
        # no _current_conversation_id set
        assert agent._session_resource_context() == ''


# --------------------------------------------------------------------------
# 4. _audit_infrastructure_change — creates + deletes
# --------------------------------------------------------------------------

class TestAuditInfrastructureChange:
    def test_records_a_create_and_surfaces_it_in_session_context(self, app, test_user, db_session):
        from models import InfrastructureChange
        agent = _make_agent()
        agent._current_user_id = test_user.id
        agent._current_conversation_id = 'conv-xyz'

        agent._audit_infrastructure_change(
            'create_ec2_instance', {'region': 'us-east-1'},
            {'success': True, 'instance': {'InstanceId': 'i-0feedface00'}},
        )

        row = InfrastructureChange.query.filter_by(
            user_id=test_user.id, action_type='create').first()
        assert row is not None
        assert row.resource_id == 'i-0feedface00'
        assert row.resource_type == 'ec2'
        assert row.change_details['conversation_id'] == 'conv-xyz'

        ctx = agent._session_resource_context()
        assert 'i-0feedface00' in ctx
        assert 'verify with a read' in ctx

        # a different conversation does not see it
        agent._current_conversation_id = 'conv-other'
        assert agent._session_resource_context() == ''

    def test_still_records_a_delete(self, app, test_user, db_session):
        from models import InfrastructureChange
        agent = _make_agent()
        agent._current_user_id = test_user.id

        agent._audit_infrastructure_change(
            'terminate_ec2_instances', {'instance_ids': ['i-0dead']},
            {'success': True},
        )
        row = InfrastructureChange.query.filter_by(
            user_id=test_user.id, action_type='delete').first()
        assert row is not None and row.resource_id == 'i-0dead'

    def test_ignores_a_plain_read(self, app, test_user, db_session):
        from models import InfrastructureChange
        agent = _make_agent()
        agent._current_user_id = test_user.id
        agent._audit_infrastructure_change(
            'get_ec2_instances', {}, {'success': True, 'instances': []})
        assert InfrastructureChange.query.filter_by(user_id=test_user.id).count() == 0


# --------------------------------------------------------------------------
# 5. guard-note surfacing
# --------------------------------------------------------------------------

class TestGuardNotes:
    def test_repeat_guard_appends_a_note_without_replacing_the_response(self):
        agent = _make_agent()
        agent._repeat_guard_result('nmap_port_scan')   # arms a note
        out = agent._append_guard_notes('Here is your answer.')
        assert out.startswith('Here is your answer.')
        assert 'Tool-selection note' in out
        assert 'nmap_port_scan' in out

    def test_no_note_when_nothing_tripped(self):
        agent = _make_agent()
        assert agent._append_guard_notes('clean answer') == 'clean answer'

    def test_repeated_not_offered_guess_is_surfaced(self):
        agent = _make_agent()
        for _ in range(3):
            agent._tool_call_log.append(
                {'tool': 'list_iam_roles', 'status': 'not_offered', 'success': False, 'error': 'x'})
        out = agent._append_guard_notes('answer')
        assert 'list_iam_roles' in out and 'guessing the wrong tool name' in out

    def test_single_not_offered_guess_is_not_surfaced(self):
        agent = _make_agent()
        agent._tool_call_log.append(
            {'tool': 'list_iam_roles', 'status': 'not_offered', 'success': False, 'error': 'x'})
        assert agent._append_guard_notes('answer') == 'answer'
