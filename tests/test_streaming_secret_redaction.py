"""Regression: a secret split across small streamed SSE chunks must still be
redacted before it reaches the browser.

`redact_secrets()` only sees whatever text is in the string it's given.
Anthropic's raw `content_block_delta` events (and Kimi's per-token stream)
are often just a handful of characters, so a real key/token from
SECRET_PATTERNS (20+ chars) has a high chance of landing split across two or
more chunks and matching nothing when redacted one chunk at a time -- even
though the final assembled response is redacted correctly before being
saved to the DB. Found live-inspecting app.py's `/api/chat/stream` handler
during a 2026-09-14 scheduled audit; the same gap existed independently (and
worse -- with zero redaction at all, not just a chunk-boundary gap) in
routes/api_gateway.py's `/v1/agent`+`/v1/agent/stream` and
api/v1/conversations.py's `send_message`+`api_v1_chat_stream`.
"""
from services.secret_detector import StreamingRedactor, redact_secrets, REDACT_PLACEHOLDER


def _feed_all(redactor: StreamingRedactor, chunks) -> str:
    out = []
    for c in chunks:
        out.append(redactor.feed(c))
    out.append(redactor.flush())
    return ''.join(out)


def test_secret_split_across_two_tiny_chunks_is_still_redacted():
    key = 'AKIA' + 'A' * 16  # matches the AWS Access Key pattern
    assert len(key) == 20

    # Split the key itself across a chunk boundary -- the worst case for a
    # naive per-chunk redact_secrets() call, which would see two fragments
    # that individually match nothing.
    chunks = ['Here is a key: ' + key[:10], key[10:] + ' -- keep it safe.']
    redactor = StreamingRedactor()
    result = _feed_all(redactor, chunks)

    assert key not in result
    assert REDACT_PLACEHOLDER in result
    # Sanity: redacting the same text in one shot agrees with the streamed result.
    assert result == redact_secrets(''.join(chunks))


def test_secret_split_across_many_single_character_chunks_is_redacted():
    """Mirrors Anthropic's real content_block_delta granularity -- often a
    handful of characters per event, sometimes one."""
    key = 'sk-ant-' + 'B' * 30
    text = f'Your token is {key} -- do not share it.'
    chunks = list(text)  # one character per "SSE chunk"

    redactor = StreamingRedactor()
    result = _feed_all(redactor, chunks)

    assert key not in result
    assert REDACT_PLACEHOLDER in result


def test_flush_emits_a_secret_still_sitting_in_the_tail_window_at_stream_end():
    key = 'sk_live_' + 'C' * 24
    redactor = StreamingRedactor()
    # A single chunk shorter than TAIL_WINDOW is held back entirely by feed().
    mid_stream = redactor.feed(f'token={key}')
    assert mid_stream == ''  # nothing safe to emit yet -- still buffered

    end = redactor.flush()
    assert key not in end
    assert REDACT_PLACEHOLDER in end


def test_plain_text_with_no_secret_streams_through_unchanged():
    chunks = ['The ', 'quick ', 'brown ', 'fox ', 'jumps ', 'over ', 'the ', 'lazy ', 'dog.'] * 5
    redactor = StreamingRedactor()
    result = _feed_all(redactor, chunks)
    assert result == ''.join(chunks)


def test_redactor_instances_do_not_share_state():
    key = 'AKIA' + 'D' * 16
    a = StreamingRedactor()
    b = StreamingRedactor()
    a.feed(key)
    # b never saw the key -- its flush must be empty, not leak a's buffer.
    assert b.flush() == ''
    assert key not in a.flush()
