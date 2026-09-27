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


# ---------------------------------------------------------------------------
# Coverage for the 12 argv sites the original guard missed.
#
# The first pass guarded only ansible_playbook_run/ansible_adhoc_command,
# because _reject_flag_like's docstring asserted that playbook_path and
# host_pattern "are always placed as the first bare positional in their
# respective command lists". That is true of those two functions and false of
# six others -- ansible_playbook_syntax_check builds
# ['ansible-playbook', '--syntax-check', playbook_path] from the same
# parameter name, and the vault trio puts file_path in exactly that position.
#
# This is the third time this module-level, opt-in guard has been applied
# incompletely on its first pass (git_tools.py needed follow-ups on
# 2026-08-04 and 2026-08-12). Until scripts/check_security_invariants.py
# grows an argv check, these tests are the only thing pinning the coverage.
# ---------------------------------------------------------------------------

from src.tools.ansible_tools import (
    ansible_playbook_syntax_check,
    ansible_galaxy_install,
    ansible_vault_encrypt,
    ansible_vault_decrypt,
    ansible_vault_view,
    ansible_doc,
    ansible_ping,
    ansible_facts,
    ansible_inventory_list,
)

FLAG = '--vault-password-file=/tmp/pwned.sh'


@pytest.mark.parametrize('call', [
    pytest.param(lambda: ansible_playbook_syntax_check(playbook_path=FLAG), id='syntax_check.playbook_path'),
    pytest.param(lambda: ansible_galaxy_install(collection_name=FLAG), id='galaxy_install.collection_name'),
    pytest.param(lambda: ansible_galaxy_install(role_name=FLAG), id='galaxy_install.role_name'),
    pytest.param(lambda: ansible_galaxy_install(requirements_file=FLAG), id='galaxy_install.requirements_file'),
    pytest.param(lambda: ansible_vault_encrypt(file_path=FLAG), id='vault_encrypt.file_path'),
    pytest.param(lambda: ansible_vault_decrypt(file_path=FLAG), id='vault_decrypt.file_path'),
    pytest.param(lambda: ansible_vault_decrypt(file_path='secrets.yml', output_file=FLAG), id='vault_decrypt.output_file'),
    pytest.param(lambda: ansible_vault_view(file_path=FLAG), id='vault_view.file_path'),
    pytest.param(lambda: ansible_doc(module_name=FLAG), id='doc.module_name'),
    pytest.param(lambda: ansible_doc(module_name='ping', module_type=FLAG), id='doc.module_type'),
    pytest.param(lambda: ansible_ping(host_pattern=FLAG), id='ping.host_pattern'),
    pytest.param(lambda: ansible_facts(host_pattern=FLAG), id='facts.host_pattern'),
    pytest.param(lambda: ansible_inventory_list(inventory=FLAG), id='inventory_list.inventory'),
])
def test_flag_like_value_is_rejected(call):
    result = call()
    assert result['success'] is False
    assert 'must not start with' in result['error'], result


# ---------------------------------------------------------------------------
# Coverage for values carried by an explicit flag (`-i <inventory>`,
# `--become-user <user>`, `--limit <pattern>`) rather than a bare positional.
#
# _reject_flag_like's own docstring already claimed this class was covered
# ("values carried by an explicit flag ... since a dash-prefixed VALUE is
# still consumed as the option's own argument"), but a 2026-09-27 scheduled
# audit found 8 of these call sites built `command.extend(['-i', inventory])`
# / `['--become-user', become_user]` / `['--limit', limit]` with no guard at
# all -- the function existed and was applied to every bare positional, just
# not to the flag-carried values the same docstring already described.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('call', [
    pytest.param(lambda: ansible_playbook_run(playbook_path='site.yml', inventory=FLAG), id='playbook_run.inventory'),
    pytest.param(lambda: ansible_playbook_run(playbook_path='site.yml', limit=FLAG), id='playbook_run.limit'),
    pytest.param(lambda: ansible_playbook_run(playbook_path='site.yml', become_user=FLAG), id='playbook_run.become_user'),
    pytest.param(lambda: ansible_adhoc_command(host_pattern='all', module='ping', inventory=FLAG), id='adhoc_command.inventory'),
    pytest.param(lambda: ansible_adhoc_command(host_pattern='all', module='ping', become_user=FLAG), id='adhoc_command.become_user'),
    pytest.param(lambda: ansible_playbook_syntax_check(playbook_path='site.yml', inventory=FLAG), id='syntax_check.inventory'),
    pytest.param(lambda: ansible_ping(host_pattern='all', inventory=FLAG), id='ping.inventory'),
    pytest.param(lambda: ansible_facts(host_pattern='all', inventory=FLAG), id='facts.inventory'),
])
def test_flag_carried_value_is_rejected(call):
    result = call()
    assert result['success'] is False
    assert 'must not start with' in result['error'], result
