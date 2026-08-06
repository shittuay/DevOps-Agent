"""Regression test: infra_sync's per-user background thread must have an app context.

Root cause found 2026-08-01 via the scheduled Check Production Errors workflow:
`_run_infra_sync()` runs inside `with app.app_context():` (pushed by `_scheduler_loop`),
but that context is thread-local — it is NOT inherited by the plain
`threading.Thread` it spawns per user to run the actual sync. Every call to
`sync_user_infrastructure()` inside that thread hit Flask/SQLAlchemy code needing
an app context and failed with "Working outside of application context", silently
dropping EC2/RDS/S3/Lambda/DynamoDB/ELB/etc. sync for every user daily since at
least 2026-07-27. Fixed by passing `app` into the thread target and opening
`with app.app_context():` inside `_sync_user_safe` itself.
"""
import threading

import flask

import services.scheduler as sched


def test_sync_user_safe_has_app_context_in_its_own_thread(app, monkeypatch):
    """_sync_user_safe must open its own app context — the caller's doesn't propagate."""
    seen = {}

    def fake_sync(user_id):
        seen['has_context'] = flask.has_app_context()
        seen['user_id'] = user_id

    monkeypatch.setattr(
        'services.infrastructure_sync.sync_user_infrastructure', fake_sync
    )

    # Spawn a real, separate thread — mirrors production exactly. Context vars
    # (Flask's app context stack) are not inherited by new threads, even though
    # the `app` fixture already has one pushed on the main thread.
    t = threading.Thread(target=sched._sync_user_safe, args=(app, 42))
    t.start()
    t.join(timeout=5)

    assert not t.is_alive(), "sync thread did not finish"
    assert seen.get('has_context') is True, (
        "sync_user_infrastructure ran without an app context in its own thread"
    )
    assert seen.get('user_id') == 42


def test_sync_user_safe_swallows_errors(app, monkeypatch):
    """A failure inside the sync call must not raise out of the thread."""
    def boom(user_id):
        raise RuntimeError("simulated AWS failure")

    monkeypatch.setattr(
        'services.infrastructure_sync.sync_user_infrastructure', boom
    )

    # Must not raise.
    sched._sync_user_safe(app, 1)
