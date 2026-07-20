"""Regression tests: a failing scheduled task must NOT retry every loop tick.

Root cause found 2026-07-20: `last_run[task]` was only advanced on success, so a
persistently failing task (db_backup hitting a non-writable BACKUP_DIR) re-ran on
every 30s scheduler tick and logged 645 errors in prod, burying real signal. The
same shape made the monitoring_tick json bug fire every 30s. The fix advances
last_run before the task runs, so a raising task backs off to its full interval.
"""
from datetime import datetime
from unittest.mock import MagicMock

import services.scheduler as sched


class _FakeEvent:
    """Stand-in for the scheduler stop Event: exits the loop after `max_ticks`."""
    def __init__(self, max_ticks):
        self.ticks = 0
        self.max_ticks = max_ticks

    def is_set(self):
        return self.ticks >= self.max_ticks

    def wait(self, timeout=None):
        self.ticks += 1

    def set(self):
        self.ticks = self.max_ticks


def test_failing_task_not_retried_every_tick(monkeypatch):
    """Every task raises; across several ticks each is attempted at most once."""
    calls = {}

    def fake_run_task(task_name, app, db):
        calls[task_name] = calls.get(task_name, 0) + 1
        raise RuntimeError("boom")

    monkeypatch.setattr(sched, '_run_task', fake_run_task)
    monkeypatch.setattr(sched, '_release_scheduler_lock', lambda: None)
    monkeypatch.setattr(sched, '_stop_event', _FakeEvent(max_ticks=4))

    sched._scheduler_loop(MagicMock(), MagicMock())

    assert calls, "expected the loop to attempt tasks at least once"
    # The invariant: within a window far shorter than any interval (min 60s),
    # no failing task is retried. Before the fix each ran 4x (once per tick).
    offenders = {k: v for k, v in calls.items() if v > 1}
    assert not offenders, f"tasks retried within their interval: {offenders}"


def test_db_backup_bad_dir_does_not_raise(monkeypatch, tmp_path):
    """A non-writable BACKUP_DIR is handled inside _run_db_backup, not propagated."""
    # Make the backup dir's parent a file so os.makedirs() fails.
    a_file = tmp_path / "not_a_dir"
    a_file.write_text("x")
    monkeypatch.setenv('BACKUP_DIR', str(a_file / "sub"))
    monkeypatch.setenv('DATABASE_URL', 'postgresql://user@localhost/db')

    # Must not raise — previously os.makedirs() threw before the try block.
    sched._run_db_backup()
