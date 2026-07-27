"""Git operations tools for DevOps Agent."""
import os
import re
from git import Repo, GitCommandError
from github import Github, GithubException
from typing import Dict, Any, List, Optional
from ..utils import get_logger
from ..utils.network_safety import assert_safe_url, UnsafeUrlError, _is_blocked_ip
import socket


logger = get_logger(__name__)


def _get_repo(repo_path: str) -> Repo:
    """Validate path and return Repo object."""
    if not os.path.isdir(repo_path):
        raise ValueError(f"Path does not exist: {repo_path}")
    try:
        return Repo(repo_path)
    except Exception:
        raise ValueError(f"Not a git repository: {repo_path}")


def _validate_git_url(url: str) -> bool:
    """Whitelist https:// and git@... URLs, blocking file://, local paths, and
    hosts that resolve to loopback/link-local/metadata addresses (SSRF guard —
    git's HTTP transport issues a real outbound GET to /info/refs before
    failing, which would otherwise leak responses from internal services like
    the cloud metadata endpoint)."""
    https_match = re.match(r'^https?://', url)
    ssh_match = re.match(r'^git@([\w.\-]+):', url)
    if not https_match and not ssh_match:
        return False

    if https_match:
        try:
            assert_safe_url(url)
        except UnsafeUrlError as e:
            logger.warning(f"Blocked git URL to unsafe host: {e}")
            return False
        return True

    hostname = ssh_match.group(1)
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        logger.warning(f"Could not resolve git SSH host {hostname!r}: {e}")
        return False
    if any(_is_blocked_ip(sockaddr[0]) for _, _, _, _, sockaddr in addr_infos):
        logger.warning(f"Blocked git SSH URL to unsafe host: {hostname}")
        return False
    return True


def _reject_flag_like(value: Optional[str], param_name: str) -> None:
    """Reject a caller-supplied ref/remote/branch value that looks like a CLI flag.

    GitPython's repo.git.<subcommand>(*args) hands args straight to the git
    executable with no shell involved (not the shell-injection class), but git
    itself parses a leading '-' as an option regardless of the caller's intent
    that it be a literal remote/branch/commit name. Several subcommands expose
    options that execute arbitrary commands: `git pull/fetch --upload-pack=<cmd>`,
    `git push --receive-pack=<cmd>`, and `git rebase --exec=<cmd>` all run <cmd>
    on this host. A value like `--upload-pack=touch$IFS/tmp/pwned` passed as the
    "remote" argument achieves command execution independent of any shell-based
    guard. Reject any value starting with '-' before it reaches GitPython.
    """
    if value and value.startswith('-'):
        raise ValueError(f"Invalid {param_name}: must not start with '-' ({value!r})")


def get_repository_status(repo_path: str) -> Dict[str, Any]:
    """
    Get status of a git repository.

    Args:
        repo_path: Path to git repository

    Returns:
        Dictionary with repository status
    """
    try:
        repo = Repo(repo_path)

        # Get current branch
        current_branch = repo.active_branch.name

        # Get modified files
        modified_files = [item.a_path for item in repo.index.diff(None)]

        # Get staged files
        staged_files = [item.a_path for item in repo.index.diff('HEAD')]

        # Get untracked files
        untracked_files = repo.untracked_files

        # Check if repo is dirty
        is_dirty = repo.is_dirty()

        return {
            'success': True,
            'repo_path': repo_path,
            'current_branch': current_branch,
            'is_dirty': is_dirty,
            'modified_files': modified_files,
            'staged_files': staged_files,
            'untracked_files': untracked_files,
            'total_changes': len(modified_files) + len(staged_files) + len(untracked_files)
        }

    except Exception as e:
        logger.error(f"Error getting repository status: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def list_branches(repo_path: str, remote: bool = False) -> Dict[str, Any]:
    """
    List branches in a git repository.

    Args:
        repo_path: Path to git repository
        remote: If True, list remote branches

    Returns:
        Dictionary with branch list
    """
    try:
        repo = Repo(repo_path)

        if remote:
            branches = [ref.name for ref in repo.remote().refs]
        else:
            branches = [ref.name for ref in repo.heads]

        current_branch = repo.active_branch.name

        return {
            'success': True,
            'repo_path': repo_path,
            'current_branch': current_branch,
            'branches': branches,
            'count': len(branches)
        }

    except Exception as e:
        logger.error(f"Error listing branches: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def get_commit_history(
    repo_path: str,
    limit: int = 10,
    branch: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get commit history from a repository.

    Args:
        repo_path: Path to git repository
        limit: Number of commits to retrieve
        branch: Specific branch to get history from

    Returns:
        Dictionary with commit history
    """
    try:
        repo = Repo(repo_path)

        # Get commits
        if branch:
            commits_iter = repo.iter_commits(branch, max_count=limit)
        else:
            commits_iter = repo.iter_commits(max_count=limit)

        commits = []
        for commit in commits_iter:
            commits.append({
                'sha': commit.hexsha[:8],
                'author': str(commit.author),
                'date': commit.committed_datetime.isoformat(),
                'message': commit.message.strip(),
                'files_changed': len(commit.stats.files)
            })

        return {
            'success': True,
            'repo_path': repo_path,
            'commits': commits,
            'count': len(commits)
        }

    except Exception as e:
        logger.error(f"Error getting commit history: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def get_diff(
    repo_path: str,
    commit1: Optional[str] = None,
    commit2: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get diff between commits or working directory.

    Args:
        repo_path: Path to git repository
        commit1: First commit (default: HEAD)
        commit2: Second commit (default: working directory)

    Returns:
        Dictionary with diff information
    """
    try:
        repo = Repo(repo_path)

        if commit2:
            # Diff between two commits
            diff = repo.git.diff(commit1 or 'HEAD', commit2)
            diff_type = f"{commit1 or 'HEAD'}..{commit2}"
        elif commit1:
            # Diff for specific commit
            diff = repo.git.show(commit1)
            diff_type = f"commit {commit1}"
        else:
            # Diff of working directory
            diff = repo.git.diff()
            diff_type = "working directory"

        # Truncate if too long
        if len(diff) > 10000:
            diff = diff[:10000] + "\n\n... (truncated, too long)"

        return {
            'success': True,
            'repo_path': repo_path,
            'diff_type': diff_type,
            'diff': diff,
            'lines': len(diff.split('\n'))
        }

    except Exception as e:
        logger.error(f"Error getting diff: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def list_pull_requests(
    repo_owner: str,
    repo_name: str,
    state: str = 'open',
    github_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    List pull requests from a GitHub repository.

    Args:
        repo_owner: Repository owner (user or organization)
        repo_name: Repository name
        state: PR state (open, closed, all)
        github_token: GitHub personal access token

    Returns:
        Dictionary with pull request list
    """
    try:
        if not github_token:
            return {
                'success': False,
                'error': 'GitHub token not provided'
            }

        g = Github(github_token)
        repo = g.get_repo(f"{repo_owner}/{repo_name}")

        # Get pull requests
        prs_list = repo.get_pulls(state=state)

        prs = []
        for pr in list(prs_list)[:20]:  # Limit to 20 PRs
            prs.append({
                'number': pr.number,
                'title': pr.title,
                'state': pr.state,
                'author': pr.user.login,
                'created_at': pr.created_at.isoformat(),
                'updated_at': pr.updated_at.isoformat(),
                'url': pr.html_url,
                'mergeable': pr.mergeable,
                'draft': pr.draft
            })

        return {
            'success': True,
            'repo': f"{repo_owner}/{repo_name}",
            'state': state,
            'count': len(prs),
            'pull_requests': prs
        }

    except GithubException as e:
        logger.error(f"GitHub API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'status_code': e.status
        }
    except Exception as e:
        logger.error(f"Error listing pull requests: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def get_pull_request_details(
    repo_owner: str,
    repo_name: str,
    pr_number: int,
    github_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get detailed information about a pull request.

    Args:
        repo_owner: Repository owner
        repo_name: Repository name
        pr_number: Pull request number
        github_token: GitHub personal access token

    Returns:
        Dictionary with pull request details
    """
    try:
        if not github_token:
            return {
                'success': False,
                'error': 'GitHub token not provided'
            }

        g = Github(github_token)
        repo = g.get_repo(f"{repo_owner}/{repo_name}")
        pr = repo.get_pull(pr_number)

        # Get files changed
        files_changed = []
        for file in pr.get_files():
            files_changed.append({
                'filename': file.filename,
                'status': file.status,
                'additions': file.additions,
                'deletions': file.deletions,
                'changes': file.changes
            })

        # Get reviews
        reviews = []
        for review in list(pr.get_reviews())[:10]:
            reviews.append({
                'user': review.user.login,
                'state': review.state,
                'submitted_at': review.submitted_at.isoformat() if review.submitted_at else None
            })

        return {
            'success': True,
            'pull_request': {
                'number': pr.number,
                'title': pr.title,
                'state': pr.state,
                'author': pr.user.login,
                'body': pr.body,
                'created_at': pr.created_at.isoformat(),
                'updated_at': pr.updated_at.isoformat(),
                'merged': pr.merged,
                'mergeable': pr.mergeable,
                'draft': pr.draft,
                'commits': pr.commits,
                'additions': pr.additions,
                'deletions': pr.deletions,
                'changed_files': pr.changed_files,
                'files': files_changed,
                'reviews': reviews,
                'url': pr.html_url
            }
        }

    except GithubException as e:
        logger.error(f"GitHub API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'status_code': e.status
        }
    except Exception as e:
        logger.error(f"Error getting pull request details: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


# ---------------------------------------------------------------------------
# Category 1: Repository Setup
# ---------------------------------------------------------------------------

def git_clone_repository(url: str, dest_path: str, branch: Optional[str] = None, depth: Optional[int] = None) -> Dict[str, Any]:
    """Clone a remote git repository to a local path."""
    try:
        if not _validate_git_url(url):
            return {'success': False, 'error': f'Invalid or disallowed git URL: {url}'}

        kwargs = {}
        if branch:
            kwargs['branch'] = branch
        if depth:
            kwargs['depth'] = depth

        # _validate_git_url() only checked the URL itself — git's HTTP transport
        # auto-follows redirects with no SSRF re-validation, so a validated-safe
        # host that 302s could otherwise land the clone on a blocked target
        # (e.g. the cloud metadata endpoint). -c/--config is normally blocked by
        # GitPython (arbitrary config injection risk) unless allow_unsafe_options
        # is set — safe here because multi_options is a fixed, code-controlled
        # value, never derived from caller input (branch/depth are the only
        # user-influenced kwargs, and they aren't config/upload-pack options).
        repo = Repo.clone_from(
            url, dest_path,
            multi_options=['-c', 'http.followRedirects=false'],
            allow_unsafe_options=True,
            **kwargs
        )
        return {
            'success': True,
            'repo_path': dest_path,
            'message': f'Repository cloned to {dest_path}'
        }
    except GitCommandError as e:
        logger.error(f"Error cloning repository: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error cloning repository: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_init_repository(repo_path: str, bare: bool = False) -> Dict[str, Any]:
    """Initialize a new git repository."""
    try:
        repo = Repo.init(repo_path, bare=bare)
        return {
            'success': True,
            'repo_path': repo_path,
            'bare': bare,
            'message': f'Initialized {"bare " if bare else ""}repository at {repo_path}'
        }
    except Exception as e:
        logger.error(f"Error initializing repository: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_add_remote(repo_path: str, name: str, url: str) -> Dict[str, Any]:
    """Add a remote to a git repository."""
    try:
        if not _validate_git_url(url):
            return {'success': False, 'error': f'Invalid or disallowed git URL: {url}'}

        repo = _get_repo(repo_path)
        repo.create_remote(name, url)
        return {
            'success': True,
            'remote': name,
            'url': url,
            'message': f'Remote "{name}" added with URL {url}'
        }
    except Exception as e:
        logger.error(f"Error adding remote: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# Category 2: Inspection
# ---------------------------------------------------------------------------

def git_show_commit(repo_path: str, commit_sha: str) -> Dict[str, Any]:
    """Show detailed information about a specific commit."""
    try:
        repo = _get_repo(repo_path)
        commit = repo.commit(commit_sha)
        return {
            'success': True,
            'sha': commit.hexsha,
            'author': str(commit.author),
            'date': commit.committed_datetime.isoformat(),
            'message': commit.message.strip(),
            'files_changed': list(commit.stats.files.keys()),
            'stats': commit.stats.total
        }
    except Exception as e:
        logger.error(f"Error showing commit: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_blame_file(repo_path: str, file_path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> Dict[str, Any]:
    """Show git blame for a file, optionally for a specific line range."""
    try:
        repo = _get_repo(repo_path)
        args = [file_path]
        if start_line is not None and end_line is not None:
            args = ['-L', f'{start_line},{end_line}', file_path]
        output = repo.git.blame(*args)
        if len(output) > 5000:
            output = output[:5000] + '\n... (truncated)'
        return {
            'success': True,
            'file_path': file_path,
            'blame': output,
            'lines': len(output.split('\n'))
        }
    except GitCommandError as e:
        logger.error(f"Error running git blame: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error running git blame: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_log_file(repo_path: str, file_path: str, limit: int = 10) -> Dict[str, Any]:
    """Show commit history for a specific file."""
    try:
        repo = _get_repo(repo_path)
        commits = []
        for commit in repo.iter_commits(paths=file_path, max_count=limit):
            commits.append({
                'sha': commit.hexsha[:8],
                'author': str(commit.author),
                'date': commit.committed_datetime.isoformat(),
                'message': commit.message.strip()
            })
        return {
            'success': True,
            'file_path': file_path,
            'commits': commits,
            'count': len(commits)
        }
    except Exception as e:
        logger.error(f"Error getting file log: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_show_file_at_commit(repo_path: str, commit_sha: str, file_path: str) -> Dict[str, Any]:
    """Show the contents of a file at a specific commit."""
    try:
        repo = _get_repo(repo_path)
        content = repo.git.show(f'{commit_sha}:{file_path}')
        if len(content) > 10000:
            content = content[:10000] + '\n... (truncated)'
        return {
            'success': True,
            'file_path': file_path,
            'commit_sha': commit_sha,
            'content': content,
            'lines': len(content.split('\n'))
        }
    except GitCommandError as e:
        logger.error(f"Error showing file at commit: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error showing file at commit: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_list_remotes(repo_path: str) -> Dict[str, Any]:
    """List all remotes in a git repository."""
    try:
        repo = _get_repo(repo_path)
        remotes = []
        for remote in repo.remotes:
            remotes.append({
                'name': remote.name,
                'urls': list(remote.urls)
            })
        return {
            'success': True,
            'remotes': remotes,
            'count': len(remotes)
        }
    except Exception as e:
        logger.error(f"Error listing remotes: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_get_remote_url(repo_path: str, remote_name: str = 'origin') -> Dict[str, Any]:
    """Get the URL(s) for a specific remote."""
    try:
        repo = _get_repo(repo_path)
        for remote in repo.remotes:
            if remote.name == remote_name:
                return {
                    'success': True,
                    'remote_name': remote_name,
                    'urls': list(remote.urls)
                }
        return {'success': False, 'error': f'Remote "{remote_name}" not found'}
    except Exception as e:
        logger.error(f"Error getting remote URL: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# Category 3: Branching
# ---------------------------------------------------------------------------

def git_create_branch(repo_path: str, branch_name: str, start_point: Optional[str] = None) -> Dict[str, Any]:
    """Create a new branch."""
    try:
        repo = _get_repo(repo_path)
        if start_point:
            repo.create_head(branch_name, commit=start_point)
        else:
            repo.create_head(branch_name)
        return {
            'success': True,
            'branch_name': branch_name,
            'message': f'Branch "{branch_name}" created'
        }
    except Exception as e:
        logger.error(f"Error creating branch: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_switch_branch(repo_path: str, branch_name: str) -> Dict[str, Any]:
    """Switch to a different branch."""
    try:
        _reject_flag_like(branch_name, 'branch_name')
        repo = _get_repo(repo_path)
        repo.git.checkout(branch_name)
        return {
            'success': True,
            'branch_name': branch_name,
            'message': f'Switched to branch "{branch_name}"'
        }
    except GitCommandError as e:
        logger.error(f"Error switching branch: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error switching branch: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_delete_branch(repo_path: str, branch_name: str, force: bool = False) -> Dict[str, Any]:
    """Delete a branch."""
    try:
        _reject_flag_like(branch_name, 'branch_name')
        repo = _get_repo(repo_path)
        repo.git.branch('-D' if force else '-d', branch_name)
        return {
            'success': True,
            'branch_name': branch_name,
            'force': force,
            'message': f'Branch "{branch_name}" deleted'
        }
    except GitCommandError as e:
        logger.error(f"Error deleting branch: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error deleting branch: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_merge_branch(repo_path: str, source_branch: str, message: Optional[str] = None, no_ff: bool = False) -> Dict[str, Any]:
    """Merge a branch into the current branch."""
    try:
        _reject_flag_like(source_branch, 'source_branch')
        repo = _get_repo(repo_path)
        args = []
        if no_ff:
            args.append('--no-ff')
        if message:
            args.extend(['-m', message])
        repo.git.merge(source_branch, *args)
        return {
            'success': True,
            'source_branch': source_branch,
            'message': f'Merged "{source_branch}" into current branch'
        }
    except GitCommandError as e:
        logger.error(f"Error merging branch: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error merging branch: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_rename_branch(repo_path: str, old_name: str, new_name: str) -> Dict[str, Any]:
    """Rename a branch."""
    try:
        _reject_flag_like(old_name, 'old_name')
        _reject_flag_like(new_name, 'new_name')
        repo = _get_repo(repo_path)
        repo.git.branch('-m', old_name, new_name)
        return {
            'success': True,
            'old_name': old_name,
            'new_name': new_name,
            'message': f'Branch "{old_name}" renamed to "{new_name}"'
        }
    except GitCommandError as e:
        logger.error(f"Error renaming branch: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error renaming branch: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# Category 4: Staging & Committing
# ---------------------------------------------------------------------------

def git_add_files(repo_path: str, file_paths: Optional[List[str]] = None, all: bool = False) -> Dict[str, Any]:
    """Stage files for commit."""
    try:
        repo = _get_repo(repo_path)
        if all:
            repo.git.add('--all')
            return {
                'success': True,
                'files': 'all',
                'message': 'All files staged'
            }
        else:
            if not file_paths:
                return {'success': False, 'error': 'No file paths provided and all=False'}
            repo.index.add(file_paths)
            return {
                'success': True,
                'files': file_paths,
                'message': f'{len(file_paths)} file(s) staged'
            }
    except Exception as e:
        logger.error(f"Error adding files: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_commit(repo_path: str, message: str, author: Optional[str] = None) -> Dict[str, Any]:
    """Create a commit with the staged changes."""
    try:
        repo = _get_repo(repo_path)
        args = ['-m', message]
        if author:
            args.append(f'--author={author}')
        repo.git.commit(*args)
        sha = repo.head.commit.hexsha[:8]
        return {
            'success': True,
            'sha': sha,
            'message': message
        }
    except GitCommandError as e:
        logger.error(f"Error committing: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error committing: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_reset_files(repo_path: str, file_paths: Optional[List[str]] = None) -> Dict[str, Any]:
    """Unstage files (reset from staging area)."""
    try:
        repo = _get_repo(repo_path)
        if file_paths:
            repo.git.reset('HEAD', '--', *file_paths)
            return {
                'success': True,
                'message': f'{len(file_paths)} file(s) unstaged'
            }
        else:
            repo.git.reset('HEAD')
            return {
                'success': True,
                'message': 'All staged files reset'
            }
    except GitCommandError as e:
        logger.error(f"Error resetting files: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error resetting files: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_reset_to_commit(repo_path: str, commit_sha: str, mode: str = 'mixed') -> Dict[str, Any]:
    """Reset the current branch to a specific commit."""
    try:
        if mode not in ('soft', 'mixed', 'hard'):
            return {'success': False, 'error': f'Invalid mode: {mode}. Must be soft, mixed, or hard'}
        _reject_flag_like(commit_sha, 'commit_sha')
        repo = _get_repo(repo_path)
        repo.git.reset(f'--{mode}', commit_sha)
        return {
            'success': True,
            'commit_sha': commit_sha,
            'mode': mode,
            'message': f'Reset to {commit_sha} ({mode})'
        }
    except GitCommandError as e:
        logger.error(f"Error resetting to commit: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error resetting to commit: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_amend_commit(repo_path: str, message: Optional[str] = None) -> Dict[str, Any]:
    """Amend the last commit, optionally changing the message."""
    try:
        repo = _get_repo(repo_path)
        if message:
            repo.git.commit('--amend', '-m', message)
        else:
            repo.git.commit('--amend', '--no-edit')
        sha = repo.head.commit.hexsha[:8]
        return {
            'success': True,
            'sha': sha,
            'message': message or '(unchanged)',
        }
    except GitCommandError as e:
        logger.error(f"Error amending commit: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error amending commit: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# Category 5: Remote Operations
# ---------------------------------------------------------------------------

def git_fetch(repo_path: str, remote: str = 'origin', prune: bool = False) -> Dict[str, Any]:
    """Fetch updates from a remote."""
    try:
        repo = _get_repo(repo_path)
        remote_obj = repo.remote(remote)
        kwargs = {}
        if prune:
            kwargs['prune'] = True
        remote_obj.fetch(**kwargs)
        return {
            'success': True,
            'remote': remote,
            'message': f'Fetched from "{remote}"' + (' with prune' if prune else '')
        }
    except GitCommandError as e:
        logger.error(f"Error fetching: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error fetching: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_pull(repo_path: str, remote: str = 'origin', branch: Optional[str] = None, rebase: bool = False) -> Dict[str, Any]:
    """Pull changes from a remote."""
    try:
        _reject_flag_like(remote, 'remote')
        _reject_flag_like(branch, 'branch')
        repo = _get_repo(repo_path)
        args = [remote]
        if branch:
            args.append(branch)
        if rebase:
            args.append('--rebase')
        repo.git.pull(*args)
        return {
            'success': True,
            'remote': remote,
            'branch': branch,
            'message': f'Pulled from "{remote}"' + (f'/{branch}' if branch else '') + (' with rebase' if rebase else '')
        }
    except GitCommandError as e:
        logger.error(f"Error pulling: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error pulling: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_push(repo_path: str, remote: str = 'origin', branch: Optional[str] = None, set_upstream: bool = False) -> Dict[str, Any]:
    """Push changes to a remote."""
    try:
        _reject_flag_like(remote, 'remote')
        _reject_flag_like(branch, 'branch')
        repo = _get_repo(repo_path)
        args = [remote]
        if branch:
            args.append(branch)
        if set_upstream:
            args.append('--set-upstream')
        repo.git.push(*args)
        return {
            'success': True,
            'remote': remote,
            'branch': branch,
            'message': f'Pushed to "{remote}"' + (f'/{branch}' if branch else '')
        }
    except GitCommandError as e:
        logger.error(f"Error pushing: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error pushing: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_force_push_branch(repo_path: str, remote: str = 'origin', branch: Optional[str] = None) -> Dict[str, Any]:
    """Force push a branch to a remote. WARNING: This overwrites remote history."""
    try:
        _reject_flag_like(remote, 'remote')
        _reject_flag_like(branch, 'branch')
        repo = _get_repo(repo_path)
        branch = branch or repo.active_branch.name
        repo.git.push(remote, branch, '--force')
        return {
            'success': True,
            'remote': remote,
            'branch': branch,
            'message': f'WARNING: Force pushed "{branch}" to "{remote}". Remote history overwritten.'
        }
    except GitCommandError as e:
        logger.error(f"Error force pushing: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error force pushing: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_cherry_pick(repo_path: str, commit_sha: str) -> Dict[str, Any]:
    """Cherry-pick a commit onto the current branch."""
    try:
        _reject_flag_like(commit_sha, 'commit_sha')
        repo = _get_repo(repo_path)
        repo.git.cherry_pick(commit_sha)
        return {
            'success': True,
            'commit_sha': commit_sha,
            'message': f'Cherry-picked commit {commit_sha}'
        }
    except GitCommandError as e:
        logger.error(f"Error cherry-picking: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error cherry-picking: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# Category 6: Tags
# ---------------------------------------------------------------------------

def git_list_tags(repo_path: str, limit: int = 20) -> Dict[str, Any]:
    """List tags in a git repository."""
    try:
        repo = _get_repo(repo_path)
        tags = []
        for tag in list(reversed(repo.tags))[:limit]:
            tags.append({
                'name': tag.name,
                'commit': tag.commit.hexsha[:8],
                'date': tag.commit.committed_datetime.isoformat()
            })
        return {
            'success': True,
            'tags': tags,
            'count': len(tags)
        }
    except Exception as e:
        logger.error(f"Error listing tags: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_create_tag(repo_path: str, tag_name: str, message: Optional[str] = None, commit: Optional[str] = None) -> Dict[str, Any]:
    """Create a new tag (lightweight or annotated)."""
    try:
        repo = _get_repo(repo_path)
        if message:
            repo.create_tag(tag_name, ref=commit, message=message)
        else:
            repo.create_tag(tag_name, ref=commit)
        return {
            'success': True,
            'tag_name': tag_name,
            'annotated': bool(message),
            'message': f'Tag "{tag_name}" created'
        }
    except Exception as e:
        logger.error(f"Error creating tag: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_delete_tag(repo_path: str, tag_name: str) -> Dict[str, Any]:
    """Delete a local tag."""
    try:
        _reject_flag_like(tag_name, 'tag_name')
        repo = _get_repo(repo_path)
        repo.git.tag('-d', tag_name)
        return {
            'success': True,
            'tag_name': tag_name,
            'message': f'Tag "{tag_name}" deleted'
        }
    except GitCommandError as e:
        logger.error(f"Error deleting tag: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error deleting tag: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_push_tag(repo_path: str, tag_name: str, remote: str = 'origin') -> Dict[str, Any]:
    """Push a tag to a remote."""
    try:
        _reject_flag_like(remote, 'remote')
        _reject_flag_like(tag_name, 'tag_name')
        repo = _get_repo(repo_path)
        repo.git.push(remote, tag_name)
        return {
            'success': True,
            'tag_name': tag_name,
            'remote': remote,
            'message': f'Tag "{tag_name}" pushed to "{remote}"'
        }
    except GitCommandError as e:
        logger.error(f"Error pushing tag: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error pushing tag: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# Category 7: Stashing
# ---------------------------------------------------------------------------

def git_stash_save(repo_path: str, message: Optional[str] = None, include_untracked: bool = False) -> Dict[str, Any]:
    """Stash current working directory changes."""
    try:
        repo = _get_repo(repo_path)
        args = ['push']
        if message:
            args.extend(['-m', message])
        if include_untracked:
            args.append('-u')
        repo.git.stash(*args)
        return {
            'success': True,
            'message': f'Changes stashed' + (f': {message}' if message else '')
        }
    except GitCommandError as e:
        logger.error(f"Error stashing: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error stashing: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_stash_list(repo_path: str) -> Dict[str, Any]:
    """List all stashes."""
    try:
        repo = _get_repo(repo_path)
        output = repo.git.stash('list')
        stashes = []
        if output.strip():
            for line in output.strip().split('\n'):
                parts = line.split(':', 1)
                stashes.append({
                    'index': parts[0].strip(),
                    'description': parts[1].strip() if len(parts) > 1 else ''
                })
        return {
            'success': True,
            'stashes': stashes,
            'count': len(stashes)
        }
    except Exception as e:
        logger.error(f"Error listing stashes: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_stash_apply(repo_path: str, stash_index: int = 0) -> Dict[str, Any]:
    """Apply a stash without removing it from the stash list."""
    try:
        repo = _get_repo(repo_path)
        repo.git.stash('apply', f'stash@{{{stash_index}}}')
        return {
            'success': True,
            'stash_index': stash_index,
            'message': f'Stash @{{{stash_index}}} applied'
        }
    except GitCommandError as e:
        logger.error(f"Error applying stash: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error applying stash: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_stash_drop(repo_path: str, stash_index: int = 0) -> Dict[str, Any]:
    """Drop a stash entry."""
    try:
        repo = _get_repo(repo_path)
        repo.git.stash('drop', f'stash@{{{stash_index}}}')
        return {
            'success': True,
            'stash_index': stash_index,
            'message': f'Stash @{{{stash_index}}} dropped'
        }
    except GitCommandError as e:
        logger.error(f"Error dropping stash: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error dropping stash: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# Category 8: Search
# ---------------------------------------------------------------------------

def git_grep_search(repo_path: str, pattern: str, file_pattern: Optional[str] = None) -> Dict[str, Any]:
    """Search for a pattern in tracked files using git grep."""
    try:
        repo = _get_repo(repo_path)
        args = [pattern]
        if file_pattern:
            args.extend(['--', file_pattern])
        output = repo.git.grep(*args)
        if len(output) > 5000:
            output = output[:5000] + '\n... (truncated)'
        return {
            'success': True,
            'pattern': pattern,
            'results': output,
            'lines': len(output.split('\n'))
        }
    except GitCommandError as e:
        if 'did not match' in str(e) or e.status == 1:
            return {'success': True, 'pattern': pattern, 'results': '', 'lines': 0}
        logger.error(f"Error running git grep: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error running git grep: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_search_commits(repo_path: str, query: str, limit: int = 10) -> Dict[str, Any]:
    """Search commit messages for a pattern."""
    try:
        repo = _get_repo(repo_path)
        output = repo.git.log(f'--grep={query}', f'--max-count={limit}', '--oneline')
        commits = []
        if output.strip():
            for line in output.strip().split('\n'):
                parts = line.split(' ', 1)
                commits.append({
                    'sha': parts[0],
                    'message': parts[1] if len(parts) > 1 else ''
                })
        return {
            'success': True,
            'query': query,
            'commits': commits,
            'count': len(commits)
        }
    except Exception as e:
        logger.error(f"Error searching commits: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_shortlog(repo_path: str, limit: int = 20, since: Optional[str] = None) -> Dict[str, Any]:
    """Show a summary of commits grouped by author."""
    try:
        repo = _get_repo(repo_path)
        args = ['-sne', f'--max-count={limit}']
        if since:
            args.append(f'--since={since}')
        output = repo.git.shortlog(*args)
        authors = []
        if output.strip():
            for line in output.strip().split('\n'):
                line = line.strip()
                parts = line.split('\t', 1)
                if len(parts) == 2:
                    count = parts[0].strip()
                    name_email = parts[1].strip()
                    email_match = re.search(r'<(.+?)>', name_email)
                    authors.append({
                        'commits': int(count),
                        'name': name_email.split('<')[0].strip() if '<' in name_email else name_email,
                        'email': email_match.group(1) if email_match else ''
                    })
        return {
            'success': True,
            'authors': authors,
            'count': len(authors)
        }
    except Exception as e:
        logger.error(f"Error running shortlog: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# Category 9: Maintenance & Advanced
# ---------------------------------------------------------------------------

def git_clean_working_directory(repo_path: str, directories: bool = False, force: bool = False) -> Dict[str, Any]:
    """Remove untracked files from the working directory. Dry run unless force=True."""
    try:
        repo = _get_repo(repo_path)
        flags = []
        if force:
            flags.append('-f')
        else:
            flags.append('-n')
        if directories:
            flags.append('-d')
        output = repo.git.clean(*flags)
        return {
            'success': True,
            'output': output,
            'force': force,
            'message': 'Cleaned working directory' if force else 'Dry run — pass force=True to actually remove files'
        }
    except GitCommandError as e:
        logger.error(f"Error cleaning working directory: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error cleaning working directory: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_revert_commit(repo_path: str, commit_sha: str) -> Dict[str, Any]:
    """Revert a commit by creating a new commit that undoes the changes."""
    try:
        _reject_flag_like(commit_sha, 'commit_sha')
        repo = _get_repo(repo_path)
        repo.git.revert(commit_sha, '--no-edit')
        return {
            'success': True,
            'commit_sha': commit_sha,
            'message': f'Reverted commit {commit_sha}'
        }
    except GitCommandError as e:
        logger.error(f"Error reverting commit: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error reverting commit: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_rebase_branch(repo_path: str, onto_branch: str) -> Dict[str, Any]:
    """Rebase the current branch onto another branch."""
    try:
        _reject_flag_like(onto_branch, 'onto_branch')
        repo = _get_repo(repo_path)
        repo.git.rebase(onto_branch)
        return {
            'success': True,
            'onto_branch': onto_branch,
            'message': f'Rebased onto "{onto_branch}"'
        }
    except GitCommandError as e:
        logger.error(f"Error rebasing: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error rebasing: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_count_objects(repo_path: str) -> Dict[str, Any]:
    """Show object store statistics for the repository."""
    try:
        repo = _get_repo(repo_path)
        output = repo.git.count_objects('-vH')
        stats = {}
        for line in output.strip().split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                stats[key.strip()] = value.strip()
        return {
            'success': True,
            'stats': stats
        }
    except Exception as e:
        logger.error(f"Error counting objects: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_reflog(repo_path: str, limit: int = 15) -> Dict[str, Any]:
    """Show the reference log for the repository."""
    try:
        repo = _get_repo(repo_path)
        output = repo.git.reflog(f'--max-count={limit}')
        entries = []
        if output.strip():
            entries = output.strip().split('\n')
        return {
            'success': True,
            'entries': entries,
            'count': len(entries)
        }
    except Exception as e:
        logger.error(f"Error getting reflog: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def git_diff_stat(repo_path: str, commit1: Optional[str] = None, commit2: Optional[str] = None) -> Dict[str, Any]:
    """Show diff statistics (files changed, insertions, deletions)."""
    try:
        repo = _get_repo(repo_path)
        if commit1 and commit2:
            output = repo.git.diff(commit1, commit2, '--stat')
        elif commit1:
            output = repo.git.diff(commit1, '--stat')
        else:
            output = repo.git.diff('--stat')
        return {
            'success': True,
            'stat': output,
            'lines': len(output.split('\n')) if output else 0
        }
    except GitCommandError as e:
        logger.error(f"Error getting diff stat: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error getting diff stat: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def get_tools() -> List[Dict[str, Any]]:
    """
    Get Git tool definitions.

    Returns:
        List of tool definitions
    """
    return [
        # --- Original 6 tools ---
        {
            'name': 'get_repository_status',
            'description': 'Get status of a git repository including modified, staged, and untracked files',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    }
                },
                'required': ['repo_path']
            },
            'handler': get_repository_status
        },
        {
            'name': 'list_branches',
            'description': 'List branches in a git repository',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'remote': {
                        'type': 'boolean',
                        'description': 'List remote branches instead of local',
                        'default': False
                    }
                },
                'required': ['repo_path']
            },
            'handler': list_branches
        },
        {
            'name': 'get_commit_history',
            'description': 'Get commit history from a git repository',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'limit': {
                        'type': 'integer',
                        'description': 'Number of commits to retrieve (default: 10)',
                        'default': 10
                    },
                    'branch': {
                        'type': 'string',
                        'description': 'Specific branch to get history from'
                    }
                },
                'required': ['repo_path']
            },
            'handler': get_commit_history
        },
        {
            'name': 'get_diff',
            'description': 'Get diff between commits or working directory changes',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'commit1': {
                        'type': 'string',
                        'description': 'First commit SHA (default: HEAD)'
                    },
                    'commit2': {
                        'type': 'string',
                        'description': 'Second commit SHA (default: working directory)'
                    }
                },
                'required': ['repo_path']
            },
            'handler': get_diff
        },
        {
            'name': 'list_pull_requests',
            'description': 'List pull requests from a GitHub repository',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_owner': {
                        'type': 'string',
                        'description': 'Repository owner (user or organization)'
                    },
                    'repo_name': {
                        'type': 'string',
                        'description': 'Repository name'
                    },
                    'state': {
                        'type': 'string',
                        'enum': ['open', 'closed', 'all'],
                        'description': 'Pull request state (default: open)',
                        'default': 'open'
                    },
                    'github_token': {
                        'type': 'string',
                        'description': 'GitHub personal access token'
                    }
                },
                'required': ['repo_owner', 'repo_name']
            },
            'handler': list_pull_requests
        },
        {
            'name': 'get_pull_request_details',
            'description': 'Get detailed information about a specific pull request',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_owner': {
                        'type': 'string',
                        'description': 'Repository owner'
                    },
                    'repo_name': {
                        'type': 'string',
                        'description': 'Repository name'
                    },
                    'pr_number': {
                        'type': 'integer',
                        'description': 'Pull request number'
                    },
                    'github_token': {
                        'type': 'string',
                        'description': 'GitHub personal access token'
                    }
                },
                'required': ['repo_owner', 'repo_name', 'pr_number']
            },
            'handler': get_pull_request_details
        },
        # --- Category 1: Repository Setup ---
        {
            'name': 'git_clone_repository',
            'description': 'Clone a remote git repository to a local path',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'url': {
                        'type': 'string',
                        'description': 'Remote repository URL (https or git@)'
                    },
                    'dest_path': {
                        'type': 'string',
                        'description': 'Local destination path'
                    },
                    'branch': {
                        'type': 'string',
                        'description': 'Branch to clone (default: default branch)'
                    },
                    'depth': {
                        'type': 'integer',
                        'description': 'Shallow clone depth (omit for full clone)'
                    }
                },
                'required': ['url', 'dest_path']
            },
            'handler': git_clone_repository
        },
        {
            'name': 'git_init_repository',
            'description': 'Initialize a new git repository',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path where the repository should be initialized'
                    },
                    'bare': {
                        'type': 'boolean',
                        'description': 'Create a bare repository (default: false)',
                        'default': False
                    }
                },
                'required': ['repo_path']
            },
            'handler': git_init_repository
        },
        {
            'name': 'git_add_remote',
            'description': 'Add a remote to a git repository',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'name': {
                        'type': 'string',
                        'description': 'Remote name (e.g., origin, upstream)'
                    },
                    'url': {
                        'type': 'string',
                        'description': 'Remote URL'
                    }
                },
                'required': ['repo_path', 'name', 'url']
            },
            'handler': git_add_remote
        },
        # --- Category 2: Inspection ---
        {
            'name': 'git_show_commit',
            'description': 'Show detailed information about a specific commit',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'commit_sha': {
                        'type': 'string',
                        'description': 'Commit SHA to inspect'
                    }
                },
                'required': ['repo_path', 'commit_sha']
            },
            'handler': git_show_commit
        },
        {
            'name': 'git_blame_file',
            'description': 'Show git blame annotations for a file, optionally for a line range',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'file_path': {
                        'type': 'string',
                        'description': 'Relative path to file within the repository'
                    },
                    'start_line': {
                        'type': 'integer',
                        'description': 'Start line number for blame range'
                    },
                    'end_line': {
                        'type': 'integer',
                        'description': 'End line number for blame range'
                    }
                },
                'required': ['repo_path', 'file_path']
            },
            'handler': git_blame_file
        },
        {
            'name': 'git_log_file',
            'description': 'Show commit history for a specific file',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'file_path': {
                        'type': 'string',
                        'description': 'Relative path to file within the repository'
                    },
                    'limit': {
                        'type': 'integer',
                        'description': 'Max number of commits to return (default: 10)',
                        'default': 10
                    }
                },
                'required': ['repo_path', 'file_path']
            },
            'handler': git_log_file
        },
        {
            'name': 'git_show_file_at_commit',
            'description': 'Show the contents of a file at a specific commit',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'commit_sha': {
                        'type': 'string',
                        'description': 'Commit SHA'
                    },
                    'file_path': {
                        'type': 'string',
                        'description': 'Relative path to file within the repository'
                    }
                },
                'required': ['repo_path', 'commit_sha', 'file_path']
            },
            'handler': git_show_file_at_commit
        },
        {
            'name': 'git_list_remotes',
            'description': 'List all remotes in a git repository',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    }
                },
                'required': ['repo_path']
            },
            'handler': git_list_remotes
        },
        {
            'name': 'git_get_remote_url',
            'description': 'Get the URL(s) for a specific remote',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'remote_name': {
                        'type': 'string',
                        'description': 'Remote name (default: origin)',
                        'default': 'origin'
                    }
                },
                'required': ['repo_path']
            },
            'handler': git_get_remote_url
        },
        # --- Category 3: Branching ---
        {
            'name': 'git_create_branch',
            'description': 'Create a new branch',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'branch_name': {
                        'type': 'string',
                        'description': 'Name for the new branch'
                    },
                    'start_point': {
                        'type': 'string',
                        'description': 'Commit or branch to start from (default: HEAD)'
                    }
                },
                'required': ['repo_path', 'branch_name']
            },
            'handler': git_create_branch
        },
        {
            'name': 'git_switch_branch',
            'description': 'Switch to a different branch',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'branch_name': {
                        'type': 'string',
                        'description': 'Branch to switch to'
                    }
                },
                'required': ['repo_path', 'branch_name']
            },
            'handler': git_switch_branch
        },
        {
            'name': 'git_delete_branch',
            'description': 'Delete a local branch',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'branch_name': {
                        'type': 'string',
                        'description': 'Branch to delete'
                    },
                    'force': {
                        'type': 'boolean',
                        'description': 'Force delete even if not fully merged (default: false)',
                        'default': False
                    }
                },
                'required': ['repo_path', 'branch_name']
            },
            'handler': git_delete_branch
        },
        {
            'name': 'git_merge_branch',
            'description': 'Merge a branch into the current branch',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'source_branch': {
                        'type': 'string',
                        'description': 'Branch to merge into the current branch'
                    },
                    'message': {
                        'type': 'string',
                        'description': 'Merge commit message'
                    },
                    'no_ff': {
                        'type': 'boolean',
                        'description': 'Create a merge commit even for fast-forward merges',
                        'default': False
                    }
                },
                'required': ['repo_path', 'source_branch']
            },
            'handler': git_merge_branch
        },
        {
            'name': 'git_rename_branch',
            'description': 'Rename a branch',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'old_name': {
                        'type': 'string',
                        'description': 'Current branch name'
                    },
                    'new_name': {
                        'type': 'string',
                        'description': 'New branch name'
                    }
                },
                'required': ['repo_path', 'old_name', 'new_name']
            },
            'handler': git_rename_branch
        },
        # --- Category 4: Staging & Committing ---
        {
            'name': 'git_add_files',
            'description': 'Stage files for commit',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'file_paths': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'List of file paths to stage'
                    },
                    'all': {
                        'type': 'boolean',
                        'description': 'Stage all changes (default: false)',
                        'default': False
                    }
                },
                'required': ['repo_path']
            },
            'handler': git_add_files
        },
        {
            'name': 'git_commit',
            'description': 'Create a commit with the staged changes',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'message': {
                        'type': 'string',
                        'description': 'Commit message'
                    },
                    'author': {
                        'type': 'string',
                        'description': 'Author in "Name <email>" format'
                    }
                },
                'required': ['repo_path', 'message']
            },
            'handler': git_commit
        },
        {
            'name': 'git_reset_files',
            'description': 'Unstage files from the staging area',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'file_paths': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'List of file paths to unstage (omit to unstage all)'
                    }
                },
                'required': ['repo_path']
            },
            'handler': git_reset_files
        },
        {
            'name': 'git_reset_to_commit',
            'description': 'Reset the current branch to a specific commit',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'commit_sha': {
                        'type': 'string',
                        'description': 'Commit SHA to reset to'
                    },
                    'mode': {
                        'type': 'string',
                        'enum': ['soft', 'mixed', 'hard'],
                        'description': 'Reset mode (default: mixed)',
                        'default': 'mixed'
                    }
                },
                'required': ['repo_path', 'commit_sha']
            },
            'handler': git_reset_to_commit
        },
        {
            'name': 'git_amend_commit',
            'description': 'Amend the last commit, optionally changing the message',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'message': {
                        'type': 'string',
                        'description': 'New commit message (omit to keep the same message)'
                    }
                },
                'required': ['repo_path']
            },
            'handler': git_amend_commit
        },
        # --- Category 5: Remote Operations ---
        {
            'name': 'git_fetch',
            'description': 'Fetch updates from a remote',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'remote': {
                        'type': 'string',
                        'description': 'Remote name (default: origin)',
                        'default': 'origin'
                    },
                    'prune': {
                        'type': 'boolean',
                        'description': 'Remove stale remote-tracking branches',
                        'default': False
                    }
                },
                'required': ['repo_path']
            },
            'handler': git_fetch
        },
        {
            'name': 'git_pull',
            'description': 'Pull changes from a remote',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'remote': {
                        'type': 'string',
                        'description': 'Remote name (default: origin)',
                        'default': 'origin'
                    },
                    'branch': {
                        'type': 'string',
                        'description': 'Branch to pull'
                    },
                    'rebase': {
                        'type': 'boolean',
                        'description': 'Use rebase instead of merge',
                        'default': False
                    }
                },
                'required': ['repo_path']
            },
            'handler': git_pull
        },
        {
            'name': 'git_push',
            'description': 'Push changes to a remote',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'remote': {
                        'type': 'string',
                        'description': 'Remote name (default: origin)',
                        'default': 'origin'
                    },
                    'branch': {
                        'type': 'string',
                        'description': 'Branch to push'
                    },
                    'set_upstream': {
                        'type': 'boolean',
                        'description': 'Set upstream tracking reference',
                        'default': False
                    }
                },
                'required': ['repo_path']
            },
            'handler': git_push
        },
        {
            'name': 'git_force_push_branch',
            'description': 'Force push a branch to a remote (WARNING: overwrites remote history)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'remote': {
                        'type': 'string',
                        'description': 'Remote name (default: origin)',
                        'default': 'origin'
                    },
                    'branch': {
                        'type': 'string',
                        'description': 'Branch to force push (default: current branch)'
                    }
                },
                'required': ['repo_path']
            },
            'handler': git_force_push_branch
        },
        {
            'name': 'git_cherry_pick',
            'description': 'Cherry-pick a commit onto the current branch',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'commit_sha': {
                        'type': 'string',
                        'description': 'Commit SHA to cherry-pick'
                    }
                },
                'required': ['repo_path', 'commit_sha']
            },
            'handler': git_cherry_pick
        },
        # --- Category 6: Tags ---
        {
            'name': 'git_list_tags',
            'description': 'List tags in a git repository',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'limit': {
                        'type': 'integer',
                        'description': 'Max number of tags to return (default: 20)',
                        'default': 20
                    }
                },
                'required': ['repo_path']
            },
            'handler': git_list_tags
        },
        {
            'name': 'git_create_tag',
            'description': 'Create a new tag (lightweight or annotated)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'tag_name': {
                        'type': 'string',
                        'description': 'Tag name'
                    },
                    'message': {
                        'type': 'string',
                        'description': 'Tag message (creates annotated tag if provided)'
                    },
                    'commit': {
                        'type': 'string',
                        'description': 'Commit to tag (default: HEAD)'
                    }
                },
                'required': ['repo_path', 'tag_name']
            },
            'handler': git_create_tag
        },
        {
            'name': 'git_delete_tag',
            'description': 'Delete a local tag',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'tag_name': {
                        'type': 'string',
                        'description': 'Tag to delete'
                    }
                },
                'required': ['repo_path', 'tag_name']
            },
            'handler': git_delete_tag
        },
        {
            'name': 'git_push_tag',
            'description': 'Push a tag to a remote',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'tag_name': {
                        'type': 'string',
                        'description': 'Tag to push'
                    },
                    'remote': {
                        'type': 'string',
                        'description': 'Remote name (default: origin)',
                        'default': 'origin'
                    }
                },
                'required': ['repo_path', 'tag_name']
            },
            'handler': git_push_tag
        },
        # --- Category 7: Stashing ---
        {
            'name': 'git_stash_save',
            'description': 'Stash current working directory changes',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'message': {
                        'type': 'string',
                        'description': 'Stash message'
                    },
                    'include_untracked': {
                        'type': 'boolean',
                        'description': 'Include untracked files in stash',
                        'default': False
                    }
                },
                'required': ['repo_path']
            },
            'handler': git_stash_save
        },
        {
            'name': 'git_stash_list',
            'description': 'List all stashes in the repository',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    }
                },
                'required': ['repo_path']
            },
            'handler': git_stash_list
        },
        {
            'name': 'git_stash_apply',
            'description': 'Apply a stash without removing it from the stash list',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'stash_index': {
                        'type': 'integer',
                        'description': 'Stash index to apply (default: 0)',
                        'default': 0
                    }
                },
                'required': ['repo_path']
            },
            'handler': git_stash_apply
        },
        {
            'name': 'git_stash_drop',
            'description': 'Drop a stash entry',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'stash_index': {
                        'type': 'integer',
                        'description': 'Stash index to drop (default: 0)',
                        'default': 0
                    }
                },
                'required': ['repo_path']
            },
            'handler': git_stash_drop
        },
        # --- Category 8: Search ---
        {
            'name': 'git_grep_search',
            'description': 'Search for a pattern in tracked files using git grep',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'pattern': {
                        'type': 'string',
                        'description': 'Search pattern'
                    },
                    'file_pattern': {
                        'type': 'string',
                        'description': 'File glob pattern to restrict search (e.g., "*.py")'
                    }
                },
                'required': ['repo_path', 'pattern']
            },
            'handler': git_grep_search
        },
        {
            'name': 'git_search_commits',
            'description': 'Search commit messages for a pattern',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'query': {
                        'type': 'string',
                        'description': 'Search query for commit messages'
                    },
                    'limit': {
                        'type': 'integer',
                        'description': 'Max number of results (default: 10)',
                        'default': 10
                    }
                },
                'required': ['repo_path', 'query']
            },
            'handler': git_search_commits
        },
        {
            'name': 'git_shortlog',
            'description': 'Show a summary of commits grouped by author',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'limit': {
                        'type': 'integer',
                        'description': 'Max number of commits to consider (default: 20)',
                        'default': 20
                    },
                    'since': {
                        'type': 'string',
                        'description': 'Only count commits after this date (e.g., "2024-01-01")'
                    }
                },
                'required': ['repo_path']
            },
            'handler': git_shortlog
        },
        # --- Category 9: Maintenance & Advanced ---
        {
            'name': 'git_clean_working_directory',
            'description': 'Remove untracked files from the working directory (dry run unless force=True)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'directories': {
                        'type': 'boolean',
                        'description': 'Also remove untracked directories',
                        'default': False
                    },
                    'force': {
                        'type': 'boolean',
                        'description': 'Actually remove files (default: dry run)',
                        'default': False
                    }
                },
                'required': ['repo_path']
            },
            'handler': git_clean_working_directory
        },
        {
            'name': 'git_revert_commit',
            'description': 'Revert a commit by creating a new commit that undoes the changes',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'commit_sha': {
                        'type': 'string',
                        'description': 'Commit SHA to revert'
                    }
                },
                'required': ['repo_path', 'commit_sha']
            },
            'handler': git_revert_commit
        },
        {
            'name': 'git_rebase_branch',
            'description': 'Rebase the current branch onto another branch',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'onto_branch': {
                        'type': 'string',
                        'description': 'Branch to rebase onto'
                    }
                },
                'required': ['repo_path', 'onto_branch']
            },
            'handler': git_rebase_branch
        },
        {
            'name': 'git_count_objects',
            'description': 'Show object store statistics for the repository',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    }
                },
                'required': ['repo_path']
            },
            'handler': git_count_objects
        },
        {
            'name': 'git_reflog',
            'description': 'Show the reference log for the repository',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'limit': {
                        'type': 'integer',
                        'description': 'Max number of entries (default: 15)',
                        'default': 15
                    }
                },
                'required': ['repo_path']
            },
            'handler': git_reflog
        },
        {
            'name': 'git_diff_stat',
            'description': 'Show diff statistics (files changed, insertions, deletions)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_path': {
                        'type': 'string',
                        'description': 'Path to git repository'
                    },
                    'commit1': {
                        'type': 'string',
                        'description': 'First commit SHA'
                    },
                    'commit2': {
                        'type': 'string',
                        'description': 'Second commit SHA'
                    }
                },
                'required': ['repo_path']
            },
            'handler': git_diff_stat
        }
    ]
