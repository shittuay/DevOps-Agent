"""Regression test for the 2026-08-25 production incident (CLAUDE_RUNBOOK.md).

gunicorn.conf.py's child_exit hook crashed the whole gunicorn arbiter (not just
one worker) when PROMETHEUS_MULTIPROC_DIR was unset, because gunicorn auto-loads
gunicorn.conf.py from its working directory even with no --config flag — so the
hook ran in production before the corresponding env var was ever wired up.
"""
import importlib.util
import os
from pathlib import Path

import pytest

_CONF_PATH = Path(__file__).resolve().parent.parent / 'gunicorn.conf.py'


def _load_gunicorn_conf():
    spec = importlib.util.spec_from_file_location('gunicorn_conf_under_test', _CONF_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_child_exit_does_not_crash_without_multiproc_dir(monkeypatch):
    monkeypatch.delenv('PROMETHEUS_MULTIPROC_DIR', raising=False)
    conf = _load_gunicorn_conf()

    class FakeWorker:
        pid = 12345

    # Must not raise — this is exactly the call gunicorn's arbiter makes on
    # every worker exit, including the very first one after a fresh deploy.
    conf.child_exit(server=None, worker=FakeWorker())


def test_child_exit_marks_process_dead_when_multiproc_dir_set(monkeypatch, tmp_path):
    monkeypatch.setenv('PROMETHEUS_MULTIPROC_DIR', str(tmp_path))
    conf = _load_gunicorn_conf()

    calls = []
    monkeypatch.setattr(conf.multiprocess, 'mark_process_dead', lambda pid: calls.append(pid))

    class FakeWorker:
        pid = 12345

    conf.child_exit(server=None, worker=FakeWorker())
    assert calls == [12345]
