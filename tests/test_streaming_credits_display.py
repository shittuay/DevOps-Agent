"""Regression test for the 2026-09-02 "it says I have 0 credits" report.

The user's real balance (confirmed via a direct DB query) was 15. The chat
streaming route's generic `except Exception` handler hardcoded
`credits_remaining: 0` into its 'done' SSE event regardless of the actual
balance — any unrelated failure (a provider timeout, a tool crash, a
malformed response) made the header badge show 0 even though nothing about
the user's actual credits had changed.

Full exercise of the streaming generator needs a live app/db/auth/SSE
harness this codebase doesn't set up for app.py's route internals — the
existing sandbox-activation regression (tests/test_sandbox_activation.py)
uses the same source-level approach for the same reason. These checks read
app.py directly rather than reimplementing this logic in a mirror function
that could silently drift from the real code.
"""
import re


def _app_source() -> str:
    with open('app.py', encoding='utf-8') as f:
        return f.read()


def test_no_hardcoded_zero_credits_on_generic_stream_error():
    """The exact bug: a generic exception handler must never hardcode 0 into
    a 'done' event's credits_remaining. The two *legitimate* 0s (an actually-
    exhausted free trial) always pair with 'trial_ended': True, never with
    the generic 'error': True used by the catch-all handler."""
    src = _app_source()
    assert "'credits_remaining': 0, 'error': True" not in src
    assert '"credits_remaining": 0, "error": true' not in src.lower().replace(' ', '')


def test_generic_stream_exception_handler_looks_up_the_real_balance():
    """The fix: the catch-all `except Exception` in the streaming route must
    query CreditService.balance() rather than assume a number."""
    src = _app_source()
    idx = src.find("except Exception as e:")
    found = False
    while idx != -1:
        window = src[idx:idx + 3000]  # handler grew on 2026-10-18 (plain fallback message)
        if "'error': True" in window or '"error": True' in window:
            if 'CreditService.balance(' in window:
                found = True
                break
        idx = src.find("except Exception as e:", idx + 1)
    assert found, (
        "no generic exception handler near an 'error': True done-event "
        "was found calling CreditService.balance() for the real credit count"
    )


def test_frontend_lockout_gated_on_trial_ended_not_raw_zero():
    """templates/index.html's non-streaming response handler must gate the
    'trial ended' input lockout on the explicit trial_ended flag the backend
    sets only when credits are genuinely exhausted — not on a raw
    credits_remaining === 0 check, which a generic error response could
    satisfy for reasons unrelated to the real balance."""
    with open('templates/index.html', encoding='utf-8') as f:
        html = f.read()
    assert 'data.credits_remaining === 0' not in html, (
        "lockout must not key off a raw credits_remaining === 0 check"
    )
    assert re.search(r'if\s*\(\s*data\.trial_ended\s*\)', html), (
        "expected the lockout branch to check data.trial_ended"
    )


def test_streaming_done_handler_only_locks_on_explicit_trial_ended():
    """The SSE 'done' handler (a separate code path from the one above) was
    never vulnerable to this exact bug, since it already gates the lockout
    banner on evt.trial_ended rather than evt.credits_remaining — this locks
    that invariant in so it can't regress alongside the other fix."""
    with open('templates/index.html', encoding='utf-8') as f:
        html = f.read()
    idx = html.find("evt.type === 'done'")
    assert idx != -1
    window = html[idx:idx + 800]
    assert 'evt.trial_ended' in window
    assert 'evt.credits_remaining === 0' not in window
