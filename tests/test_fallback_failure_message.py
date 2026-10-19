"""When the main model fails and the backup fails too, chat says so in plain words (2026-10-18).

The owner saw "Error: Error code: 401 - {'error': {'message': 'Invalid API Key'...}}": Claude
had failed, the Groq backup's key was invalid, and Groq's raw exception reached the chat.
"""
from pathlib import Path

from services.chat_service import fallback_failure_message

APP = (Path(__file__).resolve().parent.parent / 'app.py').read_text()


def test_reasons_are_named_in_plain_words():
    assert 'rate limit' in fallback_failure_message('anthropic', 'Rate limit reached. Please wait a moment.')
    assert 'out of credits' in fallback_failure_message('anthropic', 'Your credit balance is too low')
    assert 'overloaded' in fallback_failure_message('kimi', 'overloaded_error')
    msg = fallback_failure_message('anthropic', '')
    assert msg.startswith("Claude couldn't answer") and 'Nothing was changed' in msg
    assert 'Error code' not in msg


def test_stream_never_sends_the_raw_exception():
    assert "'content': str(e)" not in APP
    assert '_fallback_failure_message(mc.provider, _primary_error)' in APP
    assert APP.count("app.logger.warning('Chat: %s failed, using the backup model") == 2
