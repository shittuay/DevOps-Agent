"""
Regression test for the 2026-09-11 scheduled-audit finding: screen_message()
truncated the message to a hardcoded 3000 chars before sending it to the
Haiku semantic classifier, even though validate_message() (the check that
runs immediately before it on every real call site) allows up to
MAX_MESSAGE_LENGTH (10,000) chars. A message padded with benign filler past
char 3000 could carry a paraphrased, non-regex-matching attack that the
semantic screen never saw. Fixed by screening up to MAX_MESSAGE_LENGTH,
matching the ceiling validate_message() already enforces. See
CLAUDE_RUNBOOK.md.
"""

from unittest.mock import MagicMock, patch

from src.agent.guardrails import screen_message
from services.input_sanitizer import MAX_MESSAGE_LENGTH


def _fake_classify_response(is_harmful=False, category='safe', reason='ok'):
    block = MagicMock()
    block.type = 'tool_use'
    block.name = 'classify_message'
    block.input = {'is_harmful': is_harmful, 'category': category, 'reason': reason}
    response = MagicMock()
    response.content = [block]
    return response


class TestScreenMessageLength:
    def test_full_message_up_to_max_length_reaches_haiku(self):
        """A marker placed past the old 3000-char cutoff must still be sent
        to the classifier — the previous hardcoded slice made it invisible."""
        marker = 'IGNORE_ALL_PREVIOUS_MARKER_PAST_OLD_3000_CUTOFF'
        long_message = ('A' * (MAX_MESSAGE_LENGTH - 500)) + marker

        with patch('src.agent.guardrails.anthropic.Anthropic') as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = _fake_classify_response()
            mock_anthropic_cls.return_value = mock_client

            screen_message(long_message, api_key='fake-key-for-test')

            sent_content = mock_client.messages.create.call_args.kwargs['messages'][0]['content']
            assert marker in sent_content

    def test_message_sent_to_haiku_never_exceeds_max_message_length(self):
        """The slice is a defense-in-depth ceiling, not a smaller independent
        truncation — it should match MAX_MESSAGE_LENGTH exactly. Uses a
        distinct tail marker (not just repeated padding) so a substring
        match can't trivially pass."""
        tail_marker = 'TAIL_BEYOND_MAX_MESSAGE_LENGTH_MUST_BE_DROPPED'
        over_length_message = ('B' * MAX_MESSAGE_LENGTH) + tail_marker

        with patch('src.agent.guardrails.anthropic.Anthropic') as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = _fake_classify_response()
            mock_anthropic_cls.return_value = mock_client

            screen_message(over_length_message, api_key='fake-key-for-test')

            sent_content = mock_client.messages.create.call_args.kwargs['messages'][0]['content']
            # content wraps the message in "Classify this message:\n<message>\n...\n</message>"
            assert 'B' * MAX_MESSAGE_LENGTH in sent_content
            assert tail_marker not in sent_content

    def test_crisis_detection_still_short_circuits_before_haiku(self):
        with patch('src.agent.guardrails.anthropic.Anthropic') as mock_anthropic_cls:
            result = screen_message('I want to kill myself', api_key='fake-key-for-test')
            assert result.blocked is True
            assert result.is_crisis is True
            mock_anthropic_cls.assert_not_called()

    def test_safe_message_not_blocked(self):
        with patch('src.agent.guardrails.anthropic.Anthropic') as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = _fake_classify_response()
            mock_anthropic_cls.return_value = mock_client

            result = screen_message('Can you help me optimize my AWS costs?', api_key='fake-key-for-test')
            assert result.blocked is False
