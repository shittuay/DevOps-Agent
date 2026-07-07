"""
Regression tests for the MCP OAuth authorization-code flow (routes/mcp.py).

Covers a timezone bug where `_consume_code_db` called `.timestamp()` on a
naive UTC datetime, which Python interprets as *local* server time — silently
shifting the expiry check by the server's UTC offset and causing every code
exchange to fail with `invalid_grant` on non-UTC hosts.
"""

import time

import pytest


@pytest.fixture
def _restore_localtime():
    """Ensure TZ-dependent C functions (time.mktime, etc.) don't leak across tests."""
    yield
    time.tzset()


def test_consume_code_db_expiry_is_timezone_safe(app, db_session, test_user, monkeypatch, _restore_localtime):
    """Codes issued via _store_code_db must not appear expired due to server TZ."""
    import os
    from routes import mcp as mcp_module

    # Simulate a server running in a timezone well ahead of UTC (e.g. +14:00) —
    # the exact scenario where the naive .timestamp() bug caused instant
    # "expiry" of every authorization code.
    os.environ['TZ'] = 'Pacific/Kiritimati'
    time.tzset()

    code = 'test-code-tz-safety'
    mcp_module._store_code_db(code, test_user.id, 'https://claude.ai/callback', 'challenge123')

    record = mcp_module._consume_code_db(code)

    assert record is not None
    assert record['user_id'] == test_user.id
    # The code was just issued — it must not read as already expired.
    assert record['expires'] > time.time()
    # And it must be single-use: a second consume returns nothing.
    assert mcp_module._consume_code_db(code) is None


def test_consume_code_db_returns_none_for_unknown_code(app, db_session):
    from routes import mcp as mcp_module

    assert mcp_module._consume_code_db('does-not-exist') is None
