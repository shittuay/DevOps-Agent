"""Execution Integrity v2.0 Phase 5 — destructive-action hardening.

Rule 3 (double-confirmation), rule 4 (mutation-verification pair log),
rule 10 (destructive audit trail) + record_state_override.
"""
from unittest.mock import MagicMock, patch

import pytest

from services.mutation_verifier import (
    verify_mutation, DELETE_BACKOFF, DEFAULT_BACKOFF, DELETE_CONFIRMING_READS,
)

_NS = lambda _s: None
SG_ID = 'sg-0123456789abcdef0'
EC2_ID = 'i-0123456789abcdef0'


def _seq_call_tool(verdicts):
    """call_tool that yields one read per entry: 'gone' | 'present' | 'unknown'."""
    it = iter(verdicts)

    def ct(name, **kw):
        try:
            v = next(it)
        except StopIteration:
            v = verdicts[-1]
        if v == 'gone':
            return {'success': False, 'error_code': 'InvalidGroup.NotFound', 'error': 'x'}
        if v == 'present':
            return {'success': True, 'group_id': SG_ID}
        return {'success': False, 'error_code': 'Throttling', 'error': 'slow down'}
    return ct


# --------------------------------------------------------------------------
# Rule 3 — two consecutive confirming reads
# --------------------------------------------------------------------------

class TestDoubleConfirmation:
    def test_two_consecutive_gone_confirms(self):
        ann = verify_mutation('delete_security_group', {'group_id': SG_ID}, {'success': True},
                              call_tool=_seq_call_tool(['gone', 'gone']), sleep=_NS)
        assert ann['status'] == 'confirmed'
        assert ann['reads'] == ['gone', 'gone']
        assert ann['confirming_reads'] == DELETE_CONFIRMING_READS

    def test_single_gone_then_present_is_not_confirmed(self):
        ann = verify_mutation('delete_security_group', {'group_id': SG_ID}, {'success': True},
                              call_tool=_seq_call_tool(['gone', 'present', 'present',
                                                       'present', 'present', 'present']),
                              sleep=_NS)
        assert ann['status'] == 'unconfirmed'
        assert ann['reads'][0] == 'gone' and ann['reads'][1] == 'present'
        assert 'Re-issue the terminate' in ann['message']

    def test_streak_resets_then_reconfirms(self):
        # gone, present, gone, gone -> confirmed, but the disagreement is visible
        ann = verify_mutation('delete_security_group', {'group_id': SG_ID}, {'success': True},
                              call_tool=_seq_call_tool(['gone', 'present', 'gone', 'gone']),
                              sleep=_NS)
        assert ann['status'] == 'confirmed'
        assert ann['reads'] == ['gone', 'present', 'gone', 'gone']

    def test_persistent_unknown_read_never_confirms(self):
        ann = verify_mutation('delete_vpc', {'vpc_id': 'vpc-0123456789abcdef0'}, {'success': True},
                              call_tool=lambda n, **k: {'success': False, 'error_code': 'AccessDenied'},
                              sleep=_NS)
        assert ann['status'] == 'unconfirmed'
        assert set(ann['reads']) == {'unknown'}

    def test_ec2_terminal_state_twice_confirms(self):
        ann = verify_mutation('delete_ec2_instance', {'instance_id': EC2_ID}, {'success': True},
                              call_tool=lambda n, **k: {'success': True, 'instances': [
                                  {'instance_id': EC2_ID, 'state': 'terminated'}]},
                              sleep=_NS)
        assert ann['status'] == 'confirmed' and ann['reads'] == ['gone', 'gone']

    def test_delete_backoff_is_the_long_one(self):
        slept = []
        verify_mutation('delete_security_group', {'group_id': SG_ID}, {'success': True},
                        call_tool=_seq_call_tool(['present'] * 8), sleep=slept.append)
        assert slept == [d for d in DELETE_BACKOFF if d]  # 2,5,10,20,20
        assert sum(DELETE_BACKOFF) <= 60

    def test_create_still_uses_the_fast_backoff(self):
        slept = []
        ann = verify_mutation('create_s3_bucket', {'bucket_name': 'my-bkt'}, {'success': True},
                              call_tool=lambda n, **k: {'success': True, 'buckets': []},
                              sleep=slept.append)
        assert ann['status'] == 'unconfirmed'  # never showed up
        assert slept == [d for d in DEFAULT_BACKOFF if d]  # 1,2,5,7 — not the delete chain


# --------------------------------------------------------------------------
# agent: pair log + audit trail + override
# --------------------------------------------------------------------------

def _make_agent():
    from src.agent.core import DevOpsAgent
    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None: (True if key.endswith('.enabled') else default)
    cfg.claude_model = 'claude-sonnet-4-6'
    cfg.claude_max_tokens = 4096
    cfg.claude_temperature = 0.0
    with patch('src.agent.core.anthropic.Anthropic'):
        return DevOpsAgent(cfg)


class TestMutationPairLog:
    def test_pair_recorded_for_a_verified_delete(self):
        agent = _make_agent()
        agent._current_user_id = 1
        agent.register_tool('describe_security_group', 'x', {},
                            lambda **kw: {'success': False, 'error_code': 'InvalidGroup.NotFound'})
        with patch('time.sleep', _NS):
            agent._verify_and_annotate('delete_security_group', {'group_id': SG_ID},
                                       {'success': True})
        pairs = agent.last_mutation_pairs
        assert len(pairs) == 1
        assert pairs[0]['mutation'] == 'delete_security_group'
        assert pairs[0]['verification_status'] == 'confirmed'
        assert pairs[0]['verification_reads'] == ['gone', 'gone']


class TestDestructiveAuditTrail:
    def test_audit_trail_written_with_verification(self, app, test_user, db_session):
        from models import InfrastructureChange
        agent = _make_agent()
        agent._current_user_id = test_user.id
        agent._current_conversation_id = 'c1'

        result = {'success': True, '_verification': {
            'action': 'delete', 'status': 'confirmed', 'reads': ['gone', 'gone'],
            'resource_id': EC2_ID}}
        agent._audit_infrastructure_change('terminate_ec2_instances',
                                           {'instance_ids': [EC2_ID]}, result)

        row = InfrastructureChange.query.filter_by(
            user_id=test_user.id, action_type='delete').first()
        assert row is not None
        trail = row.change_details['audit_trail']
        assert trail['final_confirmed_state'] == 'gone'
        assert trail['user_override_flag'] is False
        assert trail['verification']['reads'] == ['gone', 'gone']
        assert 'audit_alert' not in row.change_details

    def test_verification_disagreement_sets_an_alert(self, app, test_user, db_session):
        from models import InfrastructureChange
        agent = _make_agent()
        agent._current_user_id = test_user.id
        result = {'success': True, '_verification': {
            'action': 'delete', 'status': 'unconfirmed',
            'reads': ['gone', 'present'], 'resource_id': EC2_ID}}
        agent._audit_infrastructure_change('terminate_ec2_instances',
                                           {'instance_ids': [EC2_ID]}, result)
        row = InfrastructureChange.query.filter_by(
            user_id=test_user.id, action_type='delete').first()
        assert row.change_details['audit_alert'] == 'verification_disagreement'
        assert row.change_details['audit_trail']['final_confirmed_state'] == 'still_present'

    def test_tool_request_is_redacted(self, app, test_user, db_session):
        from models import InfrastructureChange
        agent = _make_agent()
        agent._current_user_id = test_user.id
        agent._audit_infrastructure_change(
            'delete_rds_instance',
            {'db_instance_identifier': 'db', 'master_password': 'hunter2'},
            {'success': True})
        row = InfrastructureChange.query.filter_by(user_id=test_user.id).first()
        assert row.change_details['audit_trail']['tool_request']['master_password'] == '***redacted***'
        assert row.change_details['audit_trail']['tool_request']['db_instance_identifier'] == 'db'


class TestRecordStateOverride:
    def test_flips_the_flag_and_alerts(self, app, test_user, db_session):
        from models import InfrastructureChange
        agent = _make_agent()
        agent._current_user_id = test_user.id
        agent._audit_infrastructure_change('terminate_ec2_instances',
                                           {'instance_ids': [EC2_ID]},
                                           {'success': True, '_verification': {
                                               'action': 'delete', 'status': 'confirmed',
                                               'reads': ['gone', 'gone']}})

        out = agent._record_state_override_handler(EC2_ID, 'still running',
                                                   'console shows state=running')
        assert out['success'] is True
        row = InfrastructureChange.query.filter_by(resource_id=EC2_ID).first()
        assert row.change_details['audit_trail']['user_override_flag'] is True
        assert row.change_details['audit_trail']['user_corrected_state'] == 'still running'
        assert row.change_details['audit_alert'] == 'user_override'

    def test_missing_row_is_a_clean_failure(self, app, test_user, db_session):
        agent = _make_agent()
        agent._current_user_id = test_user.id
        out = agent._record_state_override_handler('i-doesnotexist', 'gone')
        assert out['success'] is False and 'no change record' in out['error']


class TestPromptAndTool:
    def test_prompt_has_the_new_guidance(self):
        from src.agent.core import STABLE_SYSTEM_PROMPT
        assert 're-issue the terminate' in STABLE_SYSTEM_PROMPT.lower()
        assert 'record_state_override' in STABLE_SYSTEM_PROMPT
        # prompt-cache invariants
        assert not STABLE_SYSTEM_PROMPT.endswith('\n')
        assert 'User Preferences and Context:' not in STABLE_SYSTEM_PROMPT

    def test_override_tool_is_always_available(self):
        from src.agent.tool_selection import ALWAYS_TOOL_NAMES
        assert 'record_state_override' in ALWAYS_TOOL_NAMES

    def test_override_tool_is_registered_low_risk(self):
        from src.agent.safety import SafetyValidator
        v = SafetyValidator().validate_tool_call('record_state_override',
                                                 {'resource_id': 'i-1', 'corrected_state': 'x'})
        assert not v.requires_confirmation
