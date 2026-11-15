"""Fixes from the 2026-11-14 scheduled review."""


def test_query_bigquery_needs_confirmation():
    # Arbitrary SQL runs DELETE/DROP/TRUNCATE with the user's credentials.
    from src.agent.safety import SafetyValidator
    result = SafetyValidator().validate_tool_call('query_bigquery', {'query': 'DROP TABLE d.t'})
    assert result.requires_confirmation
    assert result.risk_level in ('medium', 'high', 'critical')


def test_query_bigquery_not_advertised_read_only_over_mcp():
    from routes.mcp import _get_tool_annotations
    hints = _get_tool_annotations('query_bigquery')
    assert hints['readOnlyHint'] is False
    assert hints['destructiveHint'] is True


def test_learning_session_summary_is_consent_gated():
    # It sends the chat transcript to Anthropic.
    from services.ai_consent import is_ai_endpoint
    assert is_ai_endpoint('/api/learning/session-summary')
