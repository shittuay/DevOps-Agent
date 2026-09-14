"""Regression: ansible_tools functions that pass a caller-supplied path/host
pattern as a bare positional argument to `subprocess.run([...])` must reject
values that look like CLI flags.

Same argv-ambiguity class git_tools.py's `_reject_flag_like` exists to close
(see tests/test_git_tools_argument_injection.py): `subprocess.run` invokes
`ansible`/`ansible-playbook` directly with no shell, but those CLIs still
parse a leading '-' as an option regardless of the caller's intent that it be
a literal playbook path or host pattern. Flagged (not confirmed as a live
RCE) by a 2026-09-14 scheduled audit as the same shape as the already-guarded
git functions -- guarded here for defense-in-depth per this codebase's own
stated policy of closing this argv-ambiguity even without a confirmed
exploit chain for a specific flag.
"""
import pytest

from src.tools.ansible_tools import (
    _reject_flag_like,
    ansible_playbook_run,
    ansible_adhoc_command,
)


def test_reject_flag_like_blocks_leading_dash():
    with pytest.raises(ValueError):
        _reject_flag_like('--connection=local', 'host_pattern')


def test_reject_flag_like_allows_normal_values():
    _reject_flag_like('webservers', 'host_pattern')
    _reject_flag_like('/srv/playbooks/site.yml', 'playbook_path')
    _reject_flag_like(None, 'playbook_path')  # optional params are skipped


def test_playbook_run_rejects_flag_like_path():
    result = ansible_playbook_run(playbook_path='--connection=local')
    assert result['success'] is False
    assert 'must not start with' in result['error']


def test_adhoc_command_rejects_flag_like_host_pattern():
    result = ansible_adhoc_command(host_pattern='--connection=local', module='copy')
    assert result['success'] is False
    assert 'must not start with' in result['error']


def test_adhoc_command_flag_check_runs_before_module_allowlist_check():
    """A flag-like host_pattern must be rejected even paired with a disallowed
    module -- proving the guard runs first, not relying on the module
    allowlist alone to catch this class of value."""
    result = ansible_adhoc_command(host_pattern='--connection=local', module='shell')
    assert result['success'] is False
    assert 'must not start with' in result['error']


def test_playbook_run_with_normal_path_reaches_subprocess(monkeypatch):
    """A legitimate-looking playbook path should fail past the flag check
    (on execution, since ansible-playbook isn't necessarily installed here),
    proving the guard doesn't over-block normal usage."""
    result = ansible_playbook_run(playbook_path='site.yml', working_dir='/nonexistent')
    assert result['success'] is False
    assert 'must not start with' not in result.get('error', '')
