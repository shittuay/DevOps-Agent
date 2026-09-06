"""Execution Integrity Phase 3 — 60s read-result cache + low-credit warning.

services/tool_cache.py, DevOpsAgent._invoke_tool, app._low_credit_warning.
"""
import time
from unittest.mock import MagicMock, patch

import pytest

from services.tool_cache import READ_CACHE, is_read_tool, _ReadCache, TTL_SECONDS


@pytest.fixture(autouse=True)
def _clear_cache():
    READ_CACHE.clear()
    yield
    READ_CACHE.clear()


# --------------------------------------------------------------------------
# is_read_tool
# --------------------------------------------------------------------------

class TestIsReadTool:
    @pytest.mark.parametrize('name', [
        'get_ec2_instances', 'list_s3_buckets', 'describe_vpc',
        'aws_api_read', 'gcp_api_read', 'find_ami', 'search_tools',
    ])
    def test_reads(self, name):
        assert is_read_tool(name)

    @pytest.mark.parametrize('name', [
        'create_ec2_instance', 'delete_vpc', 'terminate_ec2_instances',
        'resize_ec2_instance', 'aws_api_write', 'modify_rds_instance',
        'get_secret_value', 'get_iam_credential_report', 'generate_s3_presigned_url',
    ])
    def test_not_reads(self, name):
        assert not is_read_tool(name)


# --------------------------------------------------------------------------
# _ReadCache
# --------------------------------------------------------------------------

class TestReadCache:
    def test_hit_and_per_user_isolation(self):
        c = _ReadCache()
        c.put(1, 'k', {'success': True, 'x': 1})
        assert c.get(1, 'k') == {'success': True, 'x': 1}
        assert c.get(2, 'k') is None

    def test_failed_result_not_cached(self):
        c = _ReadCache()
        c.put(1, 'k', {'success': False, 'error': 'boom'})
        assert c.get(1, 'k') is None

    def test_non_dict_result_not_cached(self):
        c = _ReadCache()
        c.put(1, 'k', 'a string')
        assert c.get(1, 'k') is None

    def test_ttl_expiry(self):
        c = _ReadCache()
        c.put(1, 'k', {'success': True})
        with patch('services.tool_cache.time.monotonic', return_value=time.monotonic() + TTL_SECONDS + 1):
            assert c.get(1, 'k') is None

    def test_invalidate_user_drops_only_that_user(self):
        c = _ReadCache()
        c.put(1, 'a', {'success': True})
        c.put(1, 'b', {'success': True})
        c.put(2, 'a', {'success': True})
        assert c.invalidate_user(1) == 2
        assert c.get(1, 'a') is None and c.get(2, 'a') is not None

    def test_bounded_eviction(self):
        c = _ReadCache()
        for i in range(600):
            c.put(1, f'k{i}', {'success': True})
        assert len(c._store) <= 512


# --------------------------------------------------------------------------
# DevOpsAgent._invoke_tool
# --------------------------------------------------------------------------

def _make_agent(cache_enabled=True):
    from src.agent.core import DevOpsAgent
    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None: (
        cache_enabled if key == 'tool_cache.enabled' else default)
    cfg.claude_model = 'claude-sonnet-4-6'
    cfg.claude_max_tokens = 4096
    cfg.claude_temperature = 0.0
    with patch('src.agent.core.anthropic.Anthropic'):
        return DevOpsAgent(cfg)


class TestInvokeTool:
    def test_read_is_cached_second_call_hits(self):
        agent = _make_agent()
        agent._current_user_id = 42
        calls = {'n': 0}

        def handler(**kw):
            calls['n'] += 1
            return {'success': True, 'instances': [calls['n']]}

        agent.register_tool('get_ec2_instances', 'x', {}, handler)
        r1 = agent._invoke_tool('get_ec2_instances', {})
        r2 = agent._invoke_tool('get_ec2_instances', {})
        assert calls['n'] == 1 and r1 == r2

    def test_different_args_are_separate_entries(self):
        agent = _make_agent()
        agent._current_user_id = 42
        calls = {'n': 0}
        agent.register_tool('get_ec2_instances', 'x', {},
                            lambda **kw: (calls.__setitem__('n', calls['n'] + 1) or {'success': True}))
        agent._invoke_tool('get_ec2_instances', {'region': 'us-east-1'})
        agent._invoke_tool('get_ec2_instances', {'region': 'eu-west-1'})
        assert calls['n'] == 2

    def test_mutation_invalidates_the_read_cache(self):
        agent = _make_agent()
        agent._current_user_id = 42
        reads = {'n': 0}
        agent.register_tool('get_ec2_instances', 'x', {},
                            lambda **kw: (reads.__setitem__('n', reads['n'] + 1) or {'success': True}))
        agent.register_tool('create_ec2_instance', 'x', {}, lambda **kw: {'success': True})

        agent._invoke_tool('get_ec2_instances', {})
        agent._invoke_tool('get_ec2_instances', {})       # cached
        assert reads['n'] == 1
        agent._invoke_tool('create_ec2_instance', {})     # invalidates
        agent._invoke_tool('get_ec2_instances', {})       # fresh
        assert reads['n'] == 2

    def test_failed_read_is_not_cached(self):
        agent = _make_agent()
        agent._current_user_id = 42
        calls = {'n': 0}
        agent.register_tool('get_ec2_instances', 'x', {},
                            lambda **kw: (calls.__setitem__('n', calls['n'] + 1) or
                                          {'success': False, 'error': 'throttled'}))
        agent._invoke_tool('get_ec2_instances', {})
        agent._invoke_tool('get_ec2_instances', {})
        assert calls['n'] == 2

    def test_kill_switch_bypasses_cache(self):
        agent = _make_agent(cache_enabled=False)
        agent._current_user_id = 42
        calls = {'n': 0}
        agent.register_tool('get_ec2_instances', 'x', {},
                            lambda **kw: (calls.__setitem__('n', calls['n'] + 1) or {'success': True}))
        agent._invoke_tool('get_ec2_instances', {})
        agent._invoke_tool('get_ec2_instances', {})
        assert calls['n'] == 2


# --------------------------------------------------------------------------
# app._low_credit_warning
# --------------------------------------------------------------------------

class TestLowCreditWarning:
    def test_none_above_threshold(self):
        from app import _low_credit_warning
        assert _low_credit_warning(6) is None
        assert _low_credit_warning(100) is None

    def test_none_at_or_below_zero(self):
        from app import _low_credit_warning
        assert _low_credit_warning(0) is None
        assert _low_credit_warning(-1) is None

    def test_warns_between_1_and_threshold(self):
        from app import _low_credit_warning
        w = _low_credit_warning(3)
        assert w['credits_remaining'] == 3 and '3 credits' in w['message']
        w1 = _low_credit_warning(1)
        assert '1 credit ' in w1['message']  # singular

    def test_none_input(self):
        from app import _low_credit_warning
        assert _low_credit_warning(None) is None
