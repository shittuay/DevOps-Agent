"""GitHub tools for DevOps Agent — comprehensive repository, issue, PR, and Actions management."""
from typing import Dict, Any, List, Optional
from ..utils import get_logger

logger = get_logger(__name__)


def _get_github_client(token: Optional[str] = None):
    """Get authenticated PyGithub client."""
    from github import Github
    from .integration_auth import credentials
    return Github(credentials('github', token=token)['token'])


# ============================================
# Repositories
# ============================================

def github_list_repos(owner: Optional[str] = None, type: str = 'all', sort: str = 'updated',
                      limit: int = 20, github_token: Optional[str] = None) -> Dict[str, Any]:
    """List repositories for authenticated user or a specific owner."""
    try:
        g = _get_github_client(github_token)
        if owner:
            user = g.get_user(owner)
            repos = user.get_repos(type=type, sort=sort)
        else:
            repos = g.get_user().get_repos(type=type, sort=sort)

        repo_list = []
        for repo in list(repos)[:limit]:
            repo_list.append({
                'full_name': repo.full_name,
                'description': repo.description,
                'language': repo.language,
                'stars': repo.stargazers_count,
                'forks': repo.forks_count,
                'private': repo.private,
                'default_branch': repo.default_branch,
                'updated_at': repo.updated_at.isoformat() if repo.updated_at else None,
                'url': repo.html_url
            })
        return {'success': True, 'count': len(repo_list), 'repositories': repo_list}
    except Exception as e:
        logger.error(f"Error listing repos: {str(e)}")
        return {'success': False, 'error': str(e)}


def github_get_repo(repo_full_name: str, github_token: Optional[str] = None) -> Dict[str, Any]:
    """Get detailed information about a repository."""
    try:
        g = _get_github_client(github_token)
        repo = g.get_repo(repo_full_name)
        return {
            'success': True,
            'repository': {
                'full_name': repo.full_name,
                'description': repo.description,
                'language': repo.language,
                'stars': repo.stargazers_count,
                'forks': repo.forks_count,
                'open_issues': repo.open_issues_count,
                'private': repo.private,
                'default_branch': repo.default_branch,
                'topics': repo.get_topics(),
                'license': repo.license.name if repo.license else None,
                'size_kb': repo.size,
                'created_at': repo.created_at.isoformat(),
                'updated_at': repo.updated_at.isoformat(),
                'url': repo.html_url,
                'clone_url': repo.clone_url,
            }
        }
    except Exception as e:
        logger.error(f"Error getting repo: {str(e)}")
        return {'success': False, 'error': str(e)}


def github_create_repo(name: str, description: str = '', private: bool = False,
                       auto_init: bool = True, github_token: Optional[str] = None) -> Dict[str, Any]:
    """Create a new GitHub repository."""
    try:
        g = _get_github_client(github_token)
        user = g.get_user()
        repo = user.create_repo(name=name, description=description, private=private, auto_init=auto_init)
        return {
            'success': True,
            'message': f'Repository {repo.full_name} created',
            'full_name': repo.full_name,
            'url': repo.html_url,
            'clone_url': repo.clone_url,
            'private': repo.private
        }
    except Exception as e:
        logger.error(f"Error creating repo: {str(e)}")
        return {'success': False, 'error': str(e)}


def github_delete_repo(repo_full_name: str, github_token: Optional[str] = None) -> Dict[str, Any]:
    """Delete a GitHub repository. This action is irreversible."""
    try:
        g = _get_github_client(github_token)
        repo = g.get_repo(repo_full_name)
        repo.delete()
        return {'success': True, 'message': f'Repository {repo_full_name} deleted'}
    except Exception as e:
        logger.error(f"Error deleting repo: {str(e)}")
        return {'success': False, 'error': str(e)}


# ============================================
# Issues
# ============================================

def github_list_issues(repo_full_name: str, state: str = 'open', labels: Optional[str] = None,
                       limit: int = 20, github_token: Optional[str] = None) -> Dict[str, Any]:
    """List issues in a repository."""
    try:
        g = _get_github_client(github_token)
        repo = g.get_repo(repo_full_name)
        kwargs = {'state': state}
        if labels:
            kwargs['labels'] = [repo.get_label(l.strip()) for l in labels.split(',')]

        issues = repo.get_issues(**kwargs)
        issue_list = []
        for issue in list(issues)[:limit]:
            if issue.pull_request:
                continue
            issue_list.append({
                'number': issue.number,
                'title': issue.title,
                'state': issue.state,
                'author': issue.user.login,
                'labels': [l.name for l in issue.labels],
                'assignees': [a.login for a in issue.assignees],
                'comments': issue.comments,
                'created_at': issue.created_at.isoformat(),
                'url': issue.html_url
            })
        return {'success': True, 'count': len(issue_list), 'issues': issue_list}
    except Exception as e:
        logger.error(f"Error listing issues: {str(e)}")
        return {'success': False, 'error': str(e)}


def github_create_issue(repo_full_name: str, title: str, body: str = '',
                        labels: Optional[str] = None, assignees: Optional[str] = None,
                        github_token: Optional[str] = None) -> Dict[str, Any]:
    """Create a new issue in a repository."""
    try:
        g = _get_github_client(github_token)
        repo = g.get_repo(repo_full_name)
        kwargs = {'title': title, 'body': body}
        if labels:
            kwargs['labels'] = [l.strip() for l in labels.split(',')]
        if assignees:
            kwargs['assignees'] = [a.strip() for a in assignees.split(',')]

        issue = repo.create_issue(**kwargs)
        return {
            'success': True,
            'message': f'Issue #{issue.number} created',
            'number': issue.number,
            'title': issue.title,
            'url': issue.html_url
        }
    except Exception as e:
        logger.error(f"Error creating issue: {str(e)}")
        return {'success': False, 'error': str(e)}


def github_close_issue(repo_full_name: str, issue_number: int, comment: Optional[str] = None,
                       github_token: Optional[str] = None) -> Dict[str, Any]:
    """Close an issue, optionally with a comment."""
    try:
        g = _get_github_client(github_token)
        repo = g.get_repo(repo_full_name)
        issue = repo.get_issue(issue_number)
        if comment:
            issue.create_comment(comment)
        issue.edit(state='closed')
        return {'success': True, 'message': f'Issue #{issue_number} closed'}
    except Exception as e:
        logger.error(f"Error closing issue: {str(e)}")
        return {'success': False, 'error': str(e)}


# ============================================
# Pull Requests
# ============================================

def github_create_pull_request(repo_full_name: str, title: str, head: str, base: str,
                               body: str = '', draft: bool = False,
                               github_token: Optional[str] = None) -> Dict[str, Any]:
    """Create a pull request."""
    try:
        g = _get_github_client(github_token)
        repo = g.get_repo(repo_full_name)
        pr = repo.create_pull(title=title, body=body, head=head, base=base, draft=draft)
        return {
            'success': True,
            'message': f'PR #{pr.number} created',
            'number': pr.number,
            'title': pr.title,
            'url': pr.html_url,
            'draft': pr.draft
        }
    except Exception as e:
        logger.error(f"Error creating PR: {str(e)}")
        return {'success': False, 'error': str(e)}


def github_merge_pull_request(repo_full_name: str, pr_number: int,
                              merge_method: str = 'merge', commit_message: Optional[str] = None,
                              github_token: Optional[str] = None) -> Dict[str, Any]:
    """Merge a pull request."""
    try:
        g = _get_github_client(github_token)
        repo = g.get_repo(repo_full_name)
        pr = repo.get_pull(pr_number)
        kwargs = {'merge_method': merge_method}
        if commit_message:
            kwargs['commit_message'] = commit_message
        result = pr.merge(**kwargs)
        return {
            'success': result.merged,
            'message': result.message,
            'sha': result.sha
        }
    except Exception as e:
        logger.error(f"Error merging PR: {str(e)}")
        return {'success': False, 'error': str(e)}


def github_close_pull_request(repo_full_name: str, pr_number: int, comment: Optional[str] = None,
                               github_token: Optional[str] = None) -> Dict[str, Any]:
    """Close a pull request without merging, optionally with a comment."""
    try:
        g = _get_github_client(github_token)
        repo = g.get_repo(repo_full_name)
        pr = repo.get_pull(pr_number)
        if comment:
            pr.create_issue_comment(comment)
        pr.edit(state='closed')
        return {'success': True, 'message': f'PR #{pr_number} closed'}
    except Exception as e:
        logger.error(f"Error closing PR: {str(e)}")
        return {'success': False, 'error': str(e)}


# ============================================
# Branches & Releases
# ============================================

def github_list_branches(repo_full_name: str, limit: int = 30,
                         github_token: Optional[str] = None) -> Dict[str, Any]:
    """List branches in a repository."""
    try:
        g = _get_github_client(github_token)
        repo = g.get_repo(repo_full_name)
        branches = []
        for b in list(repo.get_branches())[:limit]:
            branches.append({
                'name': b.name,
                'protected': b.protected,
                'sha': b.commit.sha[:8]
            })
        return {'success': True, 'count': len(branches), 'branches': branches}
    except Exception as e:
        logger.error(f"Error listing branches: {str(e)}")
        return {'success': False, 'error': str(e)}


def github_create_branch(repo_full_name: str, branch_name: str, from_branch: Optional[str] = None,
                         github_token: Optional[str] = None) -> Dict[str, Any]:
    """Create a new branch from an existing branch or default branch."""
    try:
        g = _get_github_client(github_token)
        repo = g.get_repo(repo_full_name)
        source = from_branch or repo.default_branch
        sb = repo.get_branch(source)
        repo.create_git_ref(ref=f'refs/heads/{branch_name}', sha=sb.commit.sha)
        return {
            'success': True,
            'message': f'Branch {branch_name} created from {source}',
            'branch': branch_name,
            'sha': sb.commit.sha[:8]
        }
    except Exception as e:
        logger.error(f"Error creating branch: {str(e)}")
        return {'success': False, 'error': str(e)}


def github_list_releases(repo_full_name: str, limit: int = 10,
                         github_token: Optional[str] = None) -> Dict[str, Any]:
    """List releases for a repository."""
    try:
        g = _get_github_client(github_token)
        repo = g.get_repo(repo_full_name)
        releases = []
        for r in list(repo.get_releases())[:limit]:
            releases.append({
                'tag': r.tag_name,
                'name': r.title,
                'draft': r.draft,
                'prerelease': r.prerelease,
                'author': r.author.login if r.author else None,
                'published_at': r.published_at.isoformat() if r.published_at else None,
                'url': r.html_url
            })
        return {'success': True, 'count': len(releases), 'releases': releases}
    except Exception as e:
        logger.error(f"Error listing releases: {str(e)}")
        return {'success': False, 'error': str(e)}


def github_create_release(repo_full_name: str, tag_name: str, name: str, body: str = '',
                          draft: bool = False, prerelease: bool = False,
                          target_branch: Optional[str] = None,
                          github_token: Optional[str] = None) -> Dict[str, Any]:
    """Create a new release."""
    try:
        g = _get_github_client(github_token)
        repo = g.get_repo(repo_full_name)
        kwargs = {'tag': tag_name, 'name': name, 'message': body, 'draft': draft, 'prerelease': prerelease}
        if target_branch:
            kwargs['target_commitish'] = target_branch
        release = repo.create_git_release(**kwargs)
        return {
            'success': True,
            'message': f'Release {tag_name} created',
            'tag': release.tag_name,
            'url': release.html_url
        }
    except Exception as e:
        logger.error(f"Error creating release: {str(e)}")
        return {'success': False, 'error': str(e)}


# ============================================
# GitHub Actions / Workflows
# ============================================

def github_list_workflows(repo_full_name: str, github_token: Optional[str] = None) -> Dict[str, Any]:
    """List GitHub Actions workflows in a repository."""
    try:
        g = _get_github_client(github_token)
        repo = g.get_repo(repo_full_name)
        workflows = []
        for w in repo.get_workflows():
            workflows.append({
                'id': w.id,
                'name': w.name,
                'path': w.path,
                'state': w.state,
                'url': w.html_url
            })
        return {'success': True, 'count': len(workflows), 'workflows': workflows}
    except Exception as e:
        logger.error(f"Error listing workflows: {str(e)}")
        return {'success': False, 'error': str(e)}


def github_list_workflow_runs(repo_full_name: str, workflow_id: Optional[int] = None,
                              status: Optional[str] = None, branch: Optional[str] = None,
                              limit: int = 10, github_token: Optional[str] = None) -> Dict[str, Any]:
    """List recent workflow runs (optionally filtered by workflow, status, or branch)."""
    try:
        g = _get_github_client(github_token)
        repo = g.get_repo(repo_full_name)
        kwargs = {}
        if status:
            kwargs['status'] = status
        if branch:
            kwargs['branch'] = branch

        if workflow_id:
            wf = repo.get_workflow(workflow_id)
            runs = wf.get_runs(**kwargs)
        else:
            runs = repo.get_workflow_runs(**kwargs)

        run_list = []
        for r in list(runs)[:limit]:
            run_list.append({
                'id': r.id,
                'name': r.name,
                'status': r.status,
                'conclusion': r.conclusion,
                'branch': r.head_branch,
                'event': r.event,
                'created_at': r.created_at.isoformat(),
                'url': r.html_url
            })
        return {'success': True, 'count': len(run_list), 'runs': run_list}
    except Exception as e:
        logger.error(f"Error listing workflow runs: {str(e)}")
        return {'success': False, 'error': str(e)}


def github_trigger_workflow(repo_full_name: str, workflow_id: int, ref: str = 'main',
                            inputs: Optional[Dict[str, str]] = None,
                            github_token: Optional[str] = None) -> Dict[str, Any]:
    """Trigger a workflow_dispatch event to run a GitHub Actions workflow."""
    try:
        g = _get_github_client(github_token)
        repo = g.get_repo(repo_full_name)
        wf = repo.get_workflow(workflow_id)
        result = wf.create_dispatch(ref=ref, inputs=inputs or {})
        return {
            'success': result,
            'message': f'Workflow {wf.name} triggered on {ref}',
            'workflow_id': workflow_id,
            'ref': ref
        }
    except Exception as e:
        logger.error(f"Error triggering workflow: {str(e)}")
        return {'success': False, 'error': str(e)}


# ============================================
# Collaborators
# ============================================

def github_list_collaborators(repo_full_name: str, limit: int = 30,
                              github_token: Optional[str] = None) -> Dict[str, Any]:
    """List collaborators on a repository."""
    try:
        g = _get_github_client(github_token)
        repo = g.get_repo(repo_full_name)
        collabs = []
        for c in list(repo.get_collaborators())[:limit]:
            perms = repo.get_collaborator_permission(c)
            collabs.append({
                'login': c.login,
                'permission': perms,
                'url': c.html_url
            })
        return {'success': True, 'count': len(collabs), 'collaborators': collabs}
    except Exception as e:
        logger.error(f"Error listing collaborators: {str(e)}")
        return {'success': False, 'error': str(e)}


def github_invite_collaborator(repo_full_name: str, username: str, permission: str = 'push',
                               github_token: Optional[str] = None) -> Dict[str, Any]:
    """Invite a user as a collaborator to a repository."""
    try:
        g = _get_github_client(github_token)
        repo = g.get_repo(repo_full_name)
        repo.add_to_collaborators(username, permission=permission)
        return {'success': True, 'message': f'{username} invited with {permission} access'}
    except Exception as e:
        logger.error(f"Error inviting collaborator: {str(e)}")
        return {'success': False, 'error': str(e)}


# ============================================
# Tool registration
# ============================================

def get_tools() -> List[Dict[str, Any]]:
    """Get GitHub tool definitions."""
    return [
        {
            'name': 'github_list_repos',
            'description': 'List GitHub repositories for authenticated user or a specific owner',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'owner': {'type': 'string', 'description': 'GitHub username or org (omit for authenticated user)'},
                    'type': {'type': 'string', 'enum': ['all', 'owner', 'public', 'private', 'member'], 'default': 'all'},
                    'sort': {'type': 'string', 'enum': ['created', 'updated', 'pushed', 'full_name'], 'default': 'updated'},
                    'limit': {'type': 'integer', 'description': 'Max repos to return', 'default': 20},
                    'github_token': {'type': 'string', 'description': "GitHub token (omit to use the user's connected GitHub)"},
                },
                'required': []
            },
            'handler': github_list_repos
        },
        {
            'name': 'github_get_repo',
            'description': 'Get detailed information about a GitHub repository (stars, forks, issues, license, topics)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_full_name': {'type': 'string', 'description': 'Full repo name (owner/repo)'},
                    'github_token': {'type': 'string', 'description': 'GitHub token'},
                },
                'required': ['repo_full_name']
            },
            'handler': github_get_repo
        },
        {
            'name': 'github_create_repo',
            'description': 'Create a new GitHub repository',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Repository name'},
                    'description': {'type': 'string', 'description': 'Repository description'},
                    'private': {'type': 'boolean', 'description': 'Make repository private', 'default': False},
                    'auto_init': {'type': 'boolean', 'description': 'Initialize with README', 'default': True},
                    'github_token': {'type': 'string', 'description': 'GitHub token'},
                },
                'required': ['name']
            },
            'handler': github_create_repo
        },
        {
            'name': 'github_delete_repo',
            'description': 'Delete a GitHub repository (irreversible!)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_full_name': {'type': 'string', 'description': 'Full repo name (owner/repo)'},
                    'github_token': {'type': 'string', 'description': 'GitHub token'},
                },
                'required': ['repo_full_name']
            },
            'handler': github_delete_repo
        },
        {
            'name': 'github_list_issues',
            'description': 'List issues in a GitHub repository',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_full_name': {'type': 'string', 'description': 'Full repo name (owner/repo)'},
                    'state': {'type': 'string', 'enum': ['open', 'closed', 'all'], 'default': 'open'},
                    'labels': {'type': 'string', 'description': 'Comma-separated label names to filter by'},
                    'limit': {'type': 'integer', 'default': 20},
                    'github_token': {'type': 'string', 'description': 'GitHub token'},
                },
                'required': ['repo_full_name']
            },
            'handler': github_list_issues
        },
        {
            'name': 'github_create_issue',
            'description': 'Create a new issue in a GitHub repository',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_full_name': {'type': 'string', 'description': 'Full repo name (owner/repo)'},
                    'title': {'type': 'string', 'description': 'Issue title'},
                    'body': {'type': 'string', 'description': 'Issue body/description'},
                    'labels': {'type': 'string', 'description': 'Comma-separated labels'},
                    'assignees': {'type': 'string', 'description': 'Comma-separated GitHub usernames'},
                    'github_token': {'type': 'string', 'description': 'GitHub token'},
                },
                'required': ['repo_full_name', 'title']
            },
            'handler': github_create_issue
        },
        {
            'name': 'github_close_issue',
            'description': 'Close a GitHub issue, optionally with a comment',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_full_name': {'type': 'string', 'description': 'Full repo name (owner/repo)'},
                    'issue_number': {'type': 'integer', 'description': 'Issue number'},
                    'comment': {'type': 'string', 'description': 'Optional closing comment'},
                    'github_token': {'type': 'string', 'description': 'GitHub token'},
                },
                'required': ['repo_full_name', 'issue_number']
            },
            'handler': github_close_issue
        },
        {
            'name': 'github_create_pull_request',
            'description': 'Create a pull request in a GitHub repository',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_full_name': {'type': 'string', 'description': 'Full repo name (owner/repo)'},
                    'title': {'type': 'string', 'description': 'PR title'},
                    'head': {'type': 'string', 'description': 'Source branch (e.g. feature-branch)'},
                    'base': {'type': 'string', 'description': 'Target branch (e.g. main)'},
                    'body': {'type': 'string', 'description': 'PR description'},
                    'draft': {'type': 'boolean', 'description': 'Create as draft PR', 'default': False},
                    'github_token': {'type': 'string', 'description': 'GitHub token'},
                },
                'required': ['repo_full_name', 'title', 'head', 'base']
            },
            'handler': github_create_pull_request
        },
        {
            'name': 'github_merge_pull_request',
            'description': 'Merge a pull request',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_full_name': {'type': 'string', 'description': 'Full repo name (owner/repo)'},
                    'pr_number': {'type': 'integer', 'description': 'Pull request number'},
                    'merge_method': {'type': 'string', 'enum': ['merge', 'squash', 'rebase'], 'default': 'merge'},
                    'commit_message': {'type': 'string', 'description': 'Custom merge commit message'},
                    'github_token': {'type': 'string', 'description': 'GitHub token'},
                },
                'required': ['repo_full_name', 'pr_number']
            },
            'handler': github_merge_pull_request
        },
        {
            'name': 'github_close_pull_request',
            'description': 'Close a pull request without merging, optionally with a comment',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_full_name': {'type': 'string', 'description': 'Full repo name (owner/repo)'},
                    'pr_number': {'type': 'integer', 'description': 'Pull request number'},
                    'comment': {'type': 'string', 'description': 'Optional closing comment'},
                    'github_token': {'type': 'string', 'description': 'GitHub token'},
                },
                'required': ['repo_full_name', 'pr_number']
            },
            'handler': github_close_pull_request
        },
        {
            'name': 'github_list_branches',
            'description': 'List branches in a GitHub repository',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_full_name': {'type': 'string', 'description': 'Full repo name (owner/repo)'},
                    'limit': {'type': 'integer', 'default': 30},
                    'github_token': {'type': 'string', 'description': 'GitHub token'},
                },
                'required': ['repo_full_name']
            },
            'handler': github_list_branches
        },
        {
            'name': 'github_create_branch',
            'description': 'Create a new branch in a GitHub repository',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_full_name': {'type': 'string', 'description': 'Full repo name (owner/repo)'},
                    'branch_name': {'type': 'string', 'description': 'New branch name'},
                    'from_branch': {'type': 'string', 'description': 'Source branch (defaults to default branch)'},
                    'github_token': {'type': 'string', 'description': 'GitHub token'},
                },
                'required': ['repo_full_name', 'branch_name']
            },
            'handler': github_create_branch
        },
        {
            'name': 'github_list_releases',
            'description': 'List releases for a GitHub repository',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_full_name': {'type': 'string', 'description': 'Full repo name (owner/repo)'},
                    'limit': {'type': 'integer', 'default': 10},
                    'github_token': {'type': 'string', 'description': 'GitHub token'},
                },
                'required': ['repo_full_name']
            },
            'handler': github_list_releases
        },
        {
            'name': 'github_create_release',
            'description': 'Create a new release with a tag in a GitHub repository',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_full_name': {'type': 'string', 'description': 'Full repo name (owner/repo)'},
                    'tag_name': {'type': 'string', 'description': 'Git tag name (e.g. v1.0.0)'},
                    'name': {'type': 'string', 'description': 'Release title'},
                    'body': {'type': 'string', 'description': 'Release notes'},
                    'draft': {'type': 'boolean', 'default': False},
                    'prerelease': {'type': 'boolean', 'default': False},
                    'target_branch': {'type': 'string', 'description': 'Target branch for tag'},
                    'github_token': {'type': 'string', 'description': 'GitHub token'},
                },
                'required': ['repo_full_name', 'tag_name', 'name']
            },
            'handler': github_create_release
        },
        {
            'name': 'github_list_workflows',
            'description': 'List GitHub Actions workflows in a repository',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_full_name': {'type': 'string', 'description': 'Full repo name (owner/repo)'},
                    'github_token': {'type': 'string', 'description': 'GitHub token'},
                },
                'required': ['repo_full_name']
            },
            'handler': github_list_workflows
        },
        {
            'name': 'github_list_workflow_runs',
            'description': 'List recent GitHub Actions workflow runs with optional filters',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_full_name': {'type': 'string', 'description': 'Full repo name (owner/repo)'},
                    'workflow_id': {'type': 'integer', 'description': 'Filter by workflow ID'},
                    'status': {'type': 'string', 'enum': ['completed', 'action_required', 'cancelled', 'failure', 'neutral', 'skipped', 'stale', 'success', 'timed_out', 'in_progress', 'queued', 'requested', 'waiting']},
                    'branch': {'type': 'string', 'description': 'Filter by branch'},
                    'limit': {'type': 'integer', 'default': 10},
                    'github_token': {'type': 'string', 'description': 'GitHub token'},
                },
                'required': ['repo_full_name']
            },
            'handler': github_list_workflow_runs
        },
        {
            'name': 'github_trigger_workflow',
            'description': 'Trigger a GitHub Actions workflow via workflow_dispatch event',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_full_name': {'type': 'string', 'description': 'Full repo name (owner/repo)'},
                    'workflow_id': {'type': 'integer', 'description': 'Workflow ID to trigger'},
                    'ref': {'type': 'string', 'description': 'Branch or tag to run on', 'default': 'main'},
                    'inputs': {'type': 'object', 'description': 'Workflow input parameters'},
                    'github_token': {'type': 'string', 'description': 'GitHub token'},
                },
                'required': ['repo_full_name', 'workflow_id']
            },
            'handler': github_trigger_workflow
        },
        {
            'name': 'github_list_collaborators',
            'description': 'List collaborators on a GitHub repository',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_full_name': {'type': 'string', 'description': 'Full repo name (owner/repo)'},
                    'limit': {'type': 'integer', 'default': 30},
                    'github_token': {'type': 'string', 'description': 'GitHub token'},
                },
                'required': ['repo_full_name']
            },
            'handler': github_list_collaborators
        },
        {
            'name': 'github_invite_collaborator',
            'description': 'Invite a user as a collaborator to a GitHub repository',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo_full_name': {'type': 'string', 'description': 'Full repo name (owner/repo)'},
                    'username': {'type': 'string', 'description': 'GitHub username to invite'},
                    'permission': {'type': 'string', 'enum': ['pull', 'push', 'admin', 'maintain', 'triage'], 'default': 'push'},
                    'github_token': {'type': 'string', 'description': 'GitHub token'},
                },
                'required': ['repo_full_name', 'username']
            },
            'handler': github_invite_collaborator
        },
    ]
