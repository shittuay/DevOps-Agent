"""Git operations tools for DevOps Agent."""
import os
from git import Repo, GitCommandError
from github import Github, GithubException
from typing import Dict, Any, List, Optional
from ..utils import get_logger


logger = get_logger(__name__)


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


def get_tools() -> List[Dict[str, Any]]:
    """
    Get Git tool definitions.

    Returns:
        List of tool definitions
    """
    return [
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
        }
    ]
