"""Regression: git_tools functions that pass a caller-supplied remote/branch/
commit value as a bare positional argument to GitPython's repo.git.<cmd>(...)
must reject values that look like CLI flags.

GitPython invokes the git executable directly (no shell), so this is not the
shell-injection class already covered by scripts/check_security_invariants.py
-- it's git's own argument parser treating a leading '-' as an option
regardless of the caller's intent that it be a literal ref/remote name.
Several subcommands expose options that execute arbitrary commands on this
host: `git pull/fetch --upload-pack=<cmd>`, `git push --receive-pack=<cmd>`,
and `git rebase --exec=<cmd>`. A chat-driven caller of git_pull/git_push/
git_rebase_branch (etc.) could previously pass e.g.
remote="--upload-pack=touch$IFS/tmp/pwned" and reach command execution.
"""
import pytest

from src.tools.git_tools import (
    _reject_flag_like,
    git_pull,
    git_push,
    git_force_push_branch,
    git_push_tag,
    git_rebase_branch,
    git_switch_branch,
    git_merge_branch,
    git_cherry_pick,
    git_revert_commit,
    git_grep_search,
    get_diff,
    git_diff_stat,
    git_show_file_at_commit,
    git_blame_file,
)


def test_reject_flag_like_blocks_leading_dash():
    with pytest.raises(ValueError):
        _reject_flag_like('--upload-pack=touch /tmp/pwned', 'remote')


def test_reject_flag_like_allows_normal_values():
    _reject_flag_like('origin', 'remote')
    _reject_flag_like('main', 'branch')
    _reject_flag_like(None, 'branch')  # optional params are skipped


@pytest.mark.parametrize('fn,kwargs', [
    (git_pull, {'repo_path': '/nonexistent', 'remote': '--upload-pack=touch /tmp/pwned'}),
    (git_pull, {'repo_path': '/nonexistent', 'remote': 'origin', 'branch': '--upload-pack=x'}),
    (git_push, {'repo_path': '/nonexistent', 'remote': '--receive-pack=touch /tmp/pwned'}),
    (git_force_push_branch, {'repo_path': '/nonexistent', 'remote': '--receive-pack=x'}),
    (git_push_tag, {'repo_path': '/nonexistent', 'tag_name': 'v1', 'remote': '--receive-pack=x'}),
    (git_rebase_branch, {'repo_path': '/nonexistent', 'onto_branch': '--exec=touch /tmp/pwned'}),
    (git_switch_branch, {'repo_path': '/nonexistent', 'branch_name': '--orphan'}),
    (git_merge_branch, {'repo_path': '/nonexistent', 'source_branch': '--upload-pack=x'}),
    (git_cherry_pick, {'repo_path': '/nonexistent', 'commit_sha': '--upload-pack=x'}),
    (git_revert_commit, {'repo_path': '/nonexistent', 'commit_sha': '--upload-pack=x'}),
    # `git grep --open-files-in-pager=<cmd>` execs the given pager -- live-verified RCE.
    (git_grep_search, {'repo_path': '/nonexistent', 'pattern': '--open-files-in-pager=touch /tmp/pwned'}),
    # `git diff/show --output=<file>` writes command output to an arbitrary path.
    (get_diff, {'repo_path': '/nonexistent', 'commit1': '--output=/tmp/pwned'}),
    (get_diff, {'repo_path': '/nonexistent', 'commit1': 'HEAD', 'commit2': '--output=/tmp/pwned'}),
    (git_diff_stat, {'repo_path': '/nonexistent', 'commit1': '--output=/tmp/pwned'}),
    (git_diff_stat, {'repo_path': '/nonexistent', 'commit1': 'HEAD', 'commit2': '--output=/tmp/pwned'}),
    (git_show_file_at_commit, {'repo_path': '/nonexistent', 'commit_sha': '--output=/tmp/pwned', 'file_path': 'f.txt'}),
    # `git blame --contents=<file>` echoes an arbitrary file's contents back in the response.
    (git_blame_file, {'repo_path': '/nonexistent', 'file_path': '--contents=/etc/passwd'}),
])
def test_flag_like_argument_rejected_before_touching_repo(fn, kwargs):
    """The rejection must happen before _get_repo() runs, so a bogus repo_path
    proves the flag check -- not a path error -- is what fails the call."""
    result = fn(**kwargs)
    assert result['success'] is False
    assert 'must not start with' in result['error']


def test_pull_with_normal_args_reaches_repo_validation():
    """A legitimate-looking remote/branch should fail on the repo path, not the
    flag check, proving the guard doesn't over-block normal usage."""
    result = git_pull(repo_path='/nonexistent', remote='origin', branch='main')
    assert result['success'] is False
    assert 'must not start with' not in result['error']
