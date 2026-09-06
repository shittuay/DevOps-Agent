"""Execution Integrity Phase 2 — synchronous read-back verification of creates.

services/mutation_verifier.py + DevOpsAgent._verify_and_annotate.
"""
from unittest.mock import MagicMock, patch

from services.mutation_verifier import (
    verify_mutation, is_verifiable, DEFAULT_BACKOFF, MAX_VERIFICATIONS_PER_TURN,
)

_NO_SLEEP = lambda _s: None


# --------------------------------------------------------------------------
# module: verify_mutation
# --------------------------------------------------------------------------

class TestVerifyMutation:
    def test_confirmed_when_the_read_names_the_id_back(self):
        seen = {'n': 0}

        def read(name, **kw):
            seen['n'] += 1
            if seen['n'] >= 2:  # eventual consistency — shows up on the 2nd read
                return {'success': True, 'instances': [{'instance_id': 'i-0abc123def456789'}]}
            return {'success': True, 'instances': []}

        ann = verify_mutation(
            'create_ec2_instance', {},
            {'success': True, 'details': {'instance_id': 'i-0abc123def456789'}},
            call_tool=read, sleep=_NO_SLEEP,
        )
        assert ann['status'] == 'confirmed'
        assert ann['resource_id'] == 'i-0abc123def456789'
        assert ann['via'] == 'get_ec2_instances'

    def test_unconfirmed_carries_the_exact_wording(self):
        ann = verify_mutation(
            'create_ec2_instance', {},
            {'success': True, 'details': {'instance_id': 'i-0fed210fed210fed2'}},
            call_tool=lambda n, **k: {'success': True, 'instances': []},
            sleep=_NO_SLEEP,
        )
        assert ann['status'] == 'unconfirmed'
        assert ann['message'] == (
            "Create returned ID i-0fed210fed210fed2, but I cannot confirm it via a read yet "
            "— it may still be propagating. Please check the console."
        )

    def test_read_that_raises_counts_as_not_yet_confirmed(self):
        def boom(name, **kw):
            raise RuntimeError('throttled')
        ann = verify_mutation(
            'create_ec2_instance', {},
            {'success': True, 'details': {'instance_id': 'i-00112233445566778'}},
            call_tool=boom, sleep=_NO_SLEEP,
        )
        assert ann['status'] == 'unconfirmed'

    def test_rds_and_s3_resolve_id_from_tool_input(self):
        rds = verify_mutation(
            'create_rds_instance', {'db_instance_identifier': 'prod-db'},
            {'success': True, 'message': 'creating'},
            call_tool=lambda n, **k: {'success': True, 'db_instance_identifier': 'prod-db'},
            sleep=_NO_SLEEP,
        )
        assert rds['status'] == 'confirmed' and rds['resource_id'] == 'prod-db'

        s3 = verify_mutation(
            'create_s3_bucket', {'bucket_name': 'my-bucket'},
            {'success': True},
            call_tool=lambda n, **k: {'success': True, 'bucket_name': 'my-bucket'},
            sleep=_NO_SLEEP,
        )
        assert s3['status'] == 'confirmed' and s3['resource_id'] == 'my-bucket'

    def test_read_success_but_wrong_id_is_not_a_confirmation(self):
        ann = verify_mutation(
            'create_security_group', {},
            {'success': True, 'group_id': 'sg-0a1b2c3d4e5f6a7b8'},
            call_tool=lambda n, **k: {'success': True, 'group_id': 'sg-0f1e2d3c4b5a69780'},
            sleep=_NO_SLEEP,
        )
        assert ann['status'] == 'unconfirmed'

    def test_non_verifiable_tool_returns_none(self):
        assert not is_verifiable('create_iam_role')
        assert verify_mutation('create_iam_role', {}, {'success': True},
                               call_tool=lambda *a, **k: {}, sleep=_NO_SLEEP) is None

    def test_no_resolvable_id_returns_none(self):
        assert verify_mutation('create_ec2_instance', {}, {'success': True},
                               call_tool=lambda *a, **k: {}, sleep=_NO_SLEEP) is None

    def test_backoff_is_capped_around_15s(self):
        assert sum(DEFAULT_BACKOFF) <= 16


# --------------------------------------------------------------------------
# agent: _verify_and_annotate
# --------------------------------------------------------------------------

def _make_agent(verify_enabled=True):
    from src.agent.core import DevOpsAgent
    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None: (
        verify_enabled if key == 'mutation_verify.enabled' else default
    )
    cfg.claude_model = 'claude-sonnet-4-6'
    cfg.claude_max_tokens = 4096
    cfg.claude_temperature = 0.0
    with patch('src.agent.core.anthropic.Anthropic'):
        return DevOpsAgent(cfg)


class TestVerifyAndAnnotate:
    def test_annotates_result_and_tags_the_registry(self):
        agent = _make_agent()
        agent.register_tool('get_ec2_instances', 'read', {},
                            lambda **kw: {'success': True, 'instances': [{'instance_id': 'i-00112233445566778'}]})
        # registry entry as _record_tool_call would have made it
        agent._created_resources.append({'tool': 'create_ec2_instance', 'ids': ['i-00112233445566778'], 'ts': 'x'})

        with patch('time.sleep', _NO_SLEEP):
            out = agent._verify_and_annotate(
                'create_ec2_instance', {},
                {'success': True, 'details': {'instance_id': 'i-00112233445566778'}})

        assert out['_verification']['status'] == 'confirmed'
        assert agent._created_resources[0]['verified'] is True

    def test_unconfirmed_tags_registry_false(self):
        agent = _make_agent()
        agent.register_tool('get_ec2_instances', 'read', {},
                            lambda **kw: {'success': True, 'instances': []})
        agent._created_resources.append({'tool': 'create_ec2_instance', 'ids': ['i-0deadbeef00112233'], 'ts': 'x'})
        with patch('time.sleep', _NO_SLEEP):
            out = agent._verify_and_annotate(
                'create_ec2_instance', {},
                {'success': True, 'details': {'instance_id': 'i-0deadbeef00112233'}})
        assert out['_verification']['status'] == 'unconfirmed'
        assert agent._created_resources[0]['verified'] is False

    def test_kill_switch_disables_it(self):
        agent = _make_agent(verify_enabled=False)
        out = agent._verify_and_annotate('create_ec2_instance', {},
                                         {'success': True, 'details': {'instance_id': 'i-00112233445566778'}})
        assert '_verification' not in out

    def test_sandbox_mode_skips_it(self):
        agent = _make_agent()
        agent._sandbox_mode = True
        out = agent._verify_and_annotate('create_ec2_instance', {},
                                         {'success': True, 'details': {'instance_id': 'i-00112233445566778'}})
        assert '_verification' not in out

    def test_failed_create_is_left_untouched(self):
        agent = _make_agent()
        r = {'success': False, 'error': 'ami required'}
        assert agent._verify_and_annotate('create_ec2_instance', {}, r) is r

    def test_per_turn_cap(self):
        agent = _make_agent()
        agent.register_tool('get_ec2_instances', 'read', {},
                            lambda **kw: {'success': True, 'instances': []})
        agent._verify_count = MAX_VERIFICATIONS_PER_TURN
        out = agent._verify_and_annotate('create_ec2_instance', {},
                                         {'success': True, 'details': {'instance_id': 'i-00112233445566778'}})
        assert '_verification' not in out
