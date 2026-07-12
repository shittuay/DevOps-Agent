"""
Regression tests for is_anthropic_error() failover-pattern matching.

The failover detector used two over-broad substrings — 'Unexpected error' and
'API error:' — that false-matched legitimate content and tool results,
wrongly triggering Anthropic failover and the upgrade pitch:
  - 'Unexpected error' matched any response mentioning that phrase; narrowed to
    the agent's own emoji-prefixed error '❌ Unexpected error' (core.py:1179).
  - 'API error:' matched legitimate tool results (PagerDuty/OpsGenie handlers
    return "API error: ..."); removed entirely.
"""

from services.chat_service import is_anthropic_error


class TestFailoverPatterns:
    def test_real_agent_unexpected_error_matches(self):
        assert is_anthropic_error('❌ Unexpected error: connection reset') is True

    def test_legitimate_unexpected_error_text_does_not_match(self):
        assert is_anthropic_error(
            'Your deployment hit an unexpected error in stage 3 — check the logs.'
        ) is False

    def test_pagerduty_tool_result_does_not_match(self):
        # alerting_tools returns {'error': 'API error: ...'} on provider failures
        assert is_anthropic_error('{"success": false, "error": "API error: PagerDuty 429"}') is False

    def test_genuine_anthropic_failures_still_match(self):
        for s in ('credit balance is too low', 'Rate limit reached',
                  'overloaded_error', 'Error communicating with Claude',
                  'insufficient balance'):
            assert is_anthropic_error(s) is True, s

    def test_normal_response_does_not_match(self):
        assert is_anthropic_error('Here are your 3 running EC2 instances.') is False
