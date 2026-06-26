"""Tests for Kimi/Moonshot usage logging (_log_kimi_usage in src/agent/core.py).

The point of this helper is to reveal whether the Moonshot (OpenAI-compatible)
path is getting prompt caching: it surfaces a cached-token count if the provider
reports one, and logs `cached=n/a` when the provider doesn't report caching at all.
"""
from unittest.mock import MagicMock, patch


def _agent():
    from src.agent.core import DevOpsAgent
    cfg = MagicMock()
    cfg.get.return_value = None
    cfg.claude_model = 'claude-sonnet-4-6'
    cfg.claude_max_tokens = 4096
    cfg.claude_temperature = 0.0
    with patch('src.agent.core.anthropic.Anthropic'):
        agent = DevOpsAgent(cfg)
    agent.logger = MagicMock()
    return agent


def test_flat_cached_tokens_logged():
    agent = _agent()
    usage = MagicMock(prompt_tokens=100, completion_tokens=20, total_tokens=120,
                      cached_tokens=80, prompt_tokens_details=None)
    agent._log_kimi_usage(usage)
    args = agent.logger.info.call_args.args
    assert args[1] == "Kimi usage"
    assert args[2] == 100   # prompt
    assert args[3] == 80    # cached (flat)


def test_openai_nested_cached_tokens_logged():
    agent = _agent()
    usage = MagicMock(prompt_tokens=100, completion_tokens=20, total_tokens=120,
                      prompt_tokens_details=MagicMock(cached_tokens=42))
    del usage.cached_tokens  # force the nested-lookup path
    agent._log_kimi_usage(usage, streaming=True)
    args = agent.logger.info.call_args.args
    assert args[1] == "Kimi usage (stream)"
    assert args[3] == 42    # cached (nested)


def test_no_cache_field_logs_na():
    agent = _agent()
    usage = MagicMock(prompt_tokens=100, completion_tokens=20, total_tokens=120,
                      prompt_tokens_details=None)
    del usage.cached_tokens
    agent._log_kimi_usage(usage)
    assert agent.logger.info.call_args.args[3] == 'n/a'


def test_none_usage_is_noop():
    agent = _agent()
    agent._log_kimi_usage(None)
    agent.logger.info.assert_not_called()
