"""CI/CD pipeline integration tools for DevOps Agent."""
import os
import requests
import jenkins
from github import Github, GithubException
from typing import Dict, Any, List, Optional
from ..utils import get_logger


logger = get_logger(__name__)


def trigger_jenkins_job(
    job_name: str,
    parameters: Optional[Dict[str, Any]] = None,
    jenkins_url: Optional[str] = None,
    username: Optional[str] = None,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Trigger a Jenkins job with optional parameters.

    Args:
        job_name: Name of the Jenkins job
        parameters: Dictionary of job parameters
        jenkins_url: Jenkins server URL
        username: Jenkins username
        token: Jenkins API token

    Returns:
        Dictionary with trigger result
    """
    try:
        if not all([jenkins_url, username, token]):
            return {
                'success': False,
                'error': 'Jenkins credentials not provided'
            }

        server = jenkins.Jenkins(jenkins_url, username=username, password=token)

        # Trigger build
        if parameters:
            queue_number = server.build_job(job_name, parameters)
        else:
            queue_number = server.build_job(job_name)

        return {
            'success': True,
            'job_name': job_name,
            'queue_number': queue_number,
            'message': f'Successfully triggered Jenkins job: {job_name}',
            'jenkins_url': jenkins_url
        }

    except jenkins.JenkinsException as e:
        logger.error(f"Jenkins error: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }
    except Exception as e:
        logger.error(f"Error triggering Jenkins job: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def get_jenkins_job_status(
    job_name: str,
    build_number: Optional[int] = None,
    jenkins_url: Optional[str] = None,
    username: Optional[str] = None,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get status of a Jenkins job or specific build.

    Args:
        job_name: Name of the Jenkins job
        build_number: Specific build number (optional, gets last build if not specified)
        jenkins_url: Jenkins server URL
        username: Jenkins username
        token: Jenkins API token

    Returns:
        Dictionary with job status
    """
    try:
        if not all([jenkins_url, username, token]):
            return {
                'success': False,
                'error': 'Jenkins credentials not provided'
            }

        server = jenkins.Jenkins(jenkins_url, username=username, password=token)

        # Get build info
        if build_number:
            build_info = server.get_build_info(job_name, build_number)
        else:
            build_info = server.get_job_info(job_name)['lastBuild']
            if build_info:
                build_number = build_info['number']
                build_info = server.get_build_info(job_name, build_number)
            else:
                return {
                    'success': False,
                    'error': 'No builds found for this job'
                }

        return {
            'success': True,
            'job_name': job_name,
            'build_number': build_number,
            'status': build_info['result'] or 'IN_PROGRESS',
            'building': build_info['building'],
            'duration_ms': build_info['duration'],
            'timestamp': build_info['timestamp'],
            'url': build_info['url']
        }

    except jenkins.JenkinsException as e:
        logger.error(f"Jenkins error: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }
    except Exception as e:
        logger.error(f"Error getting Jenkins job status: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def get_jenkins_build_logs(
    job_name: str,
    build_number: int,
    jenkins_url: Optional[str] = None,
    username: Optional[str] = None,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get console logs from a Jenkins build.

    Args:
        job_name: Name of the Jenkins job
        build_number: Build number
        jenkins_url: Jenkins server URL
        username: Jenkins username
        token: Jenkins API token

    Returns:
        Dictionary with build logs
    """
    try:
        if not all([jenkins_url, username, token]):
            return {
                'success': False,
                'error': 'Jenkins credentials not provided'
            }

        server = jenkins.Jenkins(jenkins_url, username=username, password=token)

        # Get console output
        logs = server.get_build_console_output(job_name, build_number)

        # Truncate if too long
        if len(logs) > 20000:
            logs = logs[-20000:] + "\n\n... (showing last 20000 characters)"

        return {
            'success': True,
            'job_name': job_name,
            'build_number': build_number,
            'logs': logs,
            'log_length': len(logs)
        }

    except jenkins.JenkinsException as e:
        logger.error(f"Jenkins error: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }
    except Exception as e:
        logger.error(f"Error getting Jenkins build logs: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def _get_jenkins_server(
    jenkins_url: Optional[str],
    username: Optional[str],
    token: Optional[str]
):
    """Build a python-jenkins server instance using args or env var fallbacks."""
    url = jenkins_url or os.environ.get('JENKINS_URL', '')
    user = username or os.environ.get('JENKINS_USERNAME', '')
    tok = token or os.environ.get('JENKINS_TOKEN', '')
    if not all([url, user, tok]):
        raise ValueError('Jenkins credentials not provided and not found in environment (JENKINS_URL, JENKINS_USERNAME, JENKINS_TOKEN)')
    return jenkins.Jenkins(url, username=user, password=tok)


def list_jenkins_jobs(
    jenkins_url: Optional[str] = None,
    username: Optional[str] = None,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """List all Jenkins jobs with their current status."""
    try:
        server = _get_jenkins_server(jenkins_url, username, token)
        jobs = server.get_jobs()
        return {
            'success': True,
            'count': len(jobs),
            'jobs': [
                {
                    'name': j['name'],
                    'url': j['url'],
                    'color': j.get('color', 'notbuilt'),  # blue=passing, red=failing, yellow=unstable
                }
                for j in jobs
            ]
        }
    except jenkins.JenkinsException as e:
        logger.error(f"Jenkins error listing jobs: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error listing Jenkins jobs: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def get_jenkins_queue(
    jenkins_url: Optional[str] = None,
    username: Optional[str] = None,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """Get the Jenkins build queue — jobs waiting to be executed."""
    try:
        server = _get_jenkins_server(jenkins_url, username, token)
        queue_info = server.get_queue_info()
        return {
            'success': True,
            'count': len(queue_info),
            'queue': [
                {
                    'id': item.get('id'),
                    'task_name': item.get('task', {}).get('name'),
                    'why': item.get('why'),
                    'stuck': item.get('stuck', False),
                    'blocked': item.get('blocked', False),
                    'buildable': item.get('buildable', False),
                    'in_queue_since': item.get('inQueueSince'),
                }
                for item in queue_info
            ]
        }
    except jenkins.JenkinsException as e:
        logger.error(f"Jenkins error: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error getting Jenkins queue: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def abort_jenkins_build(
    job_name: str,
    build_number: int,
    jenkins_url: Optional[str] = None,
    username: Optional[str] = None,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """Abort a running Jenkins build. The build must be currently in progress."""
    try:
        server = _get_jenkins_server(jenkins_url, username, token)
        server.stop_build(job_name, build_number)
        return {
            'success': True,
            'message': f'Build #{build_number} of "{job_name}" aborted successfully',
            'job_name': job_name,
            'build_number': build_number
        }
    except jenkins.JenkinsException as e:
        logger.error(f"Jenkins error: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error aborting Jenkins build: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def enable_jenkins_job(
    job_name: str,
    jenkins_url: Optional[str] = None,
    username: Optional[str] = None,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """Enable a disabled Jenkins job so it can be triggered again."""
    try:
        server = _get_jenkins_server(jenkins_url, username, token)
        server.enable_job(job_name)
        return {'success': True, 'message': f'Job "{job_name}" enabled', 'job_name': job_name}
    except jenkins.JenkinsException as e:
        logger.error(f"Jenkins error: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error enabling Jenkins job: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def disable_jenkins_job(
    job_name: str,
    jenkins_url: Optional[str] = None,
    username: Optional[str] = None,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """Disable a Jenkins job to prevent it from being triggered. Does not delete the job."""
    try:
        server = _get_jenkins_server(jenkins_url, username, token)
        server.disable_job(job_name)
        return {'success': True, 'message': f'Job "{job_name}" disabled', 'job_name': job_name}
    except jenkins.JenkinsException as e:
        logger.error(f"Jenkins error: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error disabling Jenkins job: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def get_jenkins_job_config(
    job_name: str,
    jenkins_url: Optional[str] = None,
    username: Optional[str] = None,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """Get the XML configuration of a Jenkins job (the Jenkinsfile/config.xml)."""
    try:
        server = _get_jenkins_server(jenkins_url, username, token)
        config_xml = server.get_job_config(job_name)
        return {
            'success': True,
            'job_name': job_name,
            'config_xml': config_xml,
            'length': len(config_xml)
        }
    except jenkins.JenkinsException as e:
        logger.error(f"Jenkins error: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error getting Jenkins job config: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_jenkins_nodes(
    jenkins_url: Optional[str] = None,
    username: Optional[str] = None,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """List all Jenkins build agents (nodes) and their online/offline status."""
    try:
        server = _get_jenkins_server(jenkins_url, username, token)
        nodes = server.get_nodes()
        result_nodes = []
        for node in nodes:
            try:
                info = server.get_node_info(node['name'])
                result_nodes.append({
                    'name': node['name'],
                    'offline': info.get('offline', False),
                    'temporarily_offline': info.get('temporarilyOffline', False),
                    'idle': info.get('idle', True),
                    'num_executors': info.get('numExecutors', 0),
                    'offline_cause': info.get('offlineCause', {}).get('_class', '') if info.get('offlineCause') else None,
                })
            except Exception:
                result_nodes.append({'name': node['name'], 'offline': node.get('offline', False)})
        return {'success': True, 'count': len(result_nodes), 'nodes': result_nodes}
    except jenkins.JenkinsException as e:
        logger.error(f"Jenkins error: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error listing Jenkins nodes: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_jenkins_build(
    job_name: str,
    build_number: int,
    jenkins_url: Optional[str] = None,
    username: Optional[str] = None,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a specific build record from Jenkins build history."""
    try:
        server = _get_jenkins_server(jenkins_url, username, token)
        server.delete_build(job_name, build_number)
        return {
            'success': True,
            'message': f'Build #{build_number} of "{job_name}" deleted from history',
            'job_name': job_name,
            'build_number': build_number
        }
    except jenkins.JenkinsException as e:
        logger.error(f"Jenkins error: {str(e)}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error deleting Jenkins build: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def trigger_github_workflow(
    repo_owner: str,
    repo_name: str,
    workflow_name: str,
    ref: str = 'main',
    inputs: Optional[Dict[str, Any]] = None,
    github_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Trigger a GitHub Actions workflow.

    Args:
        repo_owner: Repository owner
        repo_name: Repository name
        workflow_name: Workflow filename (e.g., 'deploy.yml')
        ref: Git ref (branch, tag, or commit)
        inputs: Workflow input parameters
        github_token: GitHub personal access token

    Returns:
        Dictionary with trigger result
    """
    try:
        if not github_token:
            return {
                'success': False,
                'error': 'GitHub token not provided'
            }

        g = Github(github_token)
        repo = g.get_repo(f"{repo_owner}/{repo_name}")

        # Get workflow
        workflows = repo.get_workflows()
        workflow = None
        for wf in workflows:
            if wf.name == workflow_name or wf.path.endswith(workflow_name):
                workflow = wf
                break

        if not workflow:
            return {
                'success': False,
                'error': f'Workflow not found: {workflow_name}'
            }

        # Trigger workflow
        success = workflow.create_dispatch(ref=ref, inputs=inputs or {})

        return {
            'success': success,
            'repo': f"{repo_owner}/{repo_name}",
            'workflow': workflow_name,
            'ref': ref,
            'message': f'Successfully triggered workflow: {workflow_name}'
        }

    except GithubException as e:
        logger.error(f"GitHub API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'status_code': e.status
        }
    except Exception as e:
        logger.error(f"Error triggering GitHub workflow: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def get_github_workflow_runs(
    repo_owner: str,
    repo_name: str,
    workflow_name: Optional[str] = None,
    status: Optional[str] = None,
    github_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get GitHub Actions workflow runs.

    Args:
        repo_owner: Repository owner
        repo_name: Repository name
        workflow_name: Filter by workflow name (optional)
        status: Filter by status (queued, in_progress, completed)
        github_token: GitHub personal access token

    Returns:
        Dictionary with workflow runs
    """
    try:
        if not github_token:
            return {
                'success': False,
                'error': 'GitHub token not provided'
            }

        g = Github(github_token)
        repo = g.get_repo(f"{repo_owner}/{repo_name}")

        # Get workflow runs
        runs_list = repo.get_workflow_runs(status=status)

        runs = []
        for run in list(runs_list)[:20]:  # Limit to 20 runs
            # Filter by workflow name if specified
            if workflow_name and workflow_name not in run.name:
                continue

            runs.append({
                'id': run.id,
                'name': run.name,
                'status': run.status,
                'conclusion': run.conclusion,
                'event': run.event,
                'branch': run.head_branch,
                'commit': run.head_sha[:8],
                'created_at': run.created_at.isoformat(),
                'updated_at': run.updated_at.isoformat(),
                'url': run.html_url
            })

        return {
            'success': True,
            'repo': f"{repo_owner}/{repo_name}",
            'count': len(runs),
            'runs': runs
        }

    except GithubException as e:
        logger.error(f"GitHub API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'status_code': e.status
        }
    except Exception as e:
        logger.error(f"Error getting workflow runs: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def _get_github_token(github_token: Optional[str] = None) -> str:
    tok = github_token or os.environ.get('GITHUB_TOKEN', '')
    if not tok:
        raise ValueError('GitHub token not provided and GITHUB_TOKEN env var not set')
    return tok


def list_github_workflows(
    repo_owner: str,
    repo_name: str,
    github_token: Optional[str] = None
) -> Dict[str, Any]:
    """List all GitHub Actions workflow definitions in a repository."""
    try:
        g = Github(_get_github_token(github_token))
        repo = g.get_repo(f"{repo_owner}/{repo_name}")
        workflows = list(repo.get_workflows())
        return {
            'success': True,
            'repo': f'{repo_owner}/{repo_name}',
            'count': len(workflows),
            'workflows': [
                {
                    'id': wf.id,
                    'name': wf.name,
                    'path': wf.path,
                    'state': wf.state,
                    'url': wf.html_url,
                    'badge_url': wf.badge_url,
                }
                for wf in workflows
            ]
        }
    except GithubException as e:
        logger.error(f"GitHub API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error listing GitHub workflows: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def get_github_workflow_run(
    repo_owner: str,
    repo_name: str,
    run_id: int,
    github_token: Optional[str] = None
) -> Dict[str, Any]:
    """Get details and status of a specific GitHub Actions workflow run by run ID."""
    try:
        g = Github(_get_github_token(github_token))
        repo = g.get_repo(f"{repo_owner}/{repo_name}")
        run = repo.get_workflow_run(run_id)
        return {
            'success': True,
            'run': {
                'id': run.id,
                'name': run.name,
                'status': run.status,
                'conclusion': run.conclusion,
                'event': run.event,
                'branch': run.head_branch,
                'commit': run.head_sha[:8],
                'created_at': run.created_at.isoformat(),
                'updated_at': run.updated_at.isoformat(),
                'run_number': run.run_number,
                'url': run.html_url,
                'jobs_url': run.jobs_url,
                'logs_url': run.logs_url,
            }
        }
    except GithubException as e:
        logger.error(f"GitHub API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error getting workflow run: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def cancel_github_workflow_run(
    repo_owner: str,
    repo_name: str,
    run_id: int,
    github_token: Optional[str] = None
) -> Dict[str, Any]:
    """Cancel an in-progress GitHub Actions workflow run."""
    try:
        tok = _get_github_token(github_token)
        resp = requests.post(
            f'https://api.github.com/repos/{repo_owner}/{repo_name}/actions/runs/{run_id}/cancel',
            headers={'Authorization': f'Bearer {tok}', 'Accept': 'application/vnd.github+json'}
        )
        if resp.status_code == 202:
            return {'success': True, 'message': f'Workflow run {run_id} cancelled', 'run_id': run_id}
        return {'success': False, 'error': f'HTTP {resp.status_code}: {resp.text}'}
    except Exception as e:
        logger.error(f"Error cancelling workflow run: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def rerun_failed_github_jobs(
    repo_owner: str,
    repo_name: str,
    run_id: int,
    github_token: Optional[str] = None
) -> Dict[str, Any]:
    """Re-run only the failed jobs in a completed GitHub Actions workflow run."""
    try:
        tok = _get_github_token(github_token)
        resp = requests.post(
            f'https://api.github.com/repos/{repo_owner}/{repo_name}/actions/runs/{run_id}/rerun-failed-jobs',
            headers={'Authorization': f'Bearer {tok}', 'Accept': 'application/vnd.github+json'}
        )
        if resp.status_code == 201:
            return {'success': True, 'message': f'Failed jobs in run {run_id} queued for re-run', 'run_id': run_id}
        return {'success': False, 'error': f'HTTP {resp.status_code}: {resp.text}'}
    except Exception as e:
        logger.error(f"Error re-running failed jobs: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_github_runners(
    repo_owner: str,
    repo_name: str,
    github_token: Optional[str] = None
) -> Dict[str, Any]:
    """List self-hosted runners registered to a repository."""
    try:
        tok = _get_github_token(github_token)
        resp = requests.get(
            f'https://api.github.com/repos/{repo_owner}/{repo_name}/actions/runners',
            headers={'Authorization': f'Bearer {tok}', 'Accept': 'application/vnd.github+json'}
        )
        resp.raise_for_status()
        data = resp.json()
        runners = data.get('runners', [])
        return {
            'success': True,
            'count': len(runners),
            'runners': [
                {
                    'id': r['id'],
                    'name': r['name'],
                    'os': r['os'],
                    'status': r['status'],
                    'busy': r['busy'],
                    'labels': [lb['name'] for lb in r.get('labels', [])],
                }
                for r in runners
            ]
        }
    except Exception as e:
        logger.error(f"Error listing GitHub runners: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_github_secrets(
    repo_owner: str,
    repo_name: str,
    github_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    List GitHub Actions secrets defined in a repository.
    NOTE: Secret values are never exposed — only names and metadata are returned.
    """
    try:
        tok = _get_github_token(github_token)
        resp = requests.get(
            f'https://api.github.com/repos/{repo_owner}/{repo_name}/actions/secrets',
            headers={'Authorization': f'Bearer {tok}', 'Accept': 'application/vnd.github+json'}
        )
        resp.raise_for_status()
        data = resp.json()
        secrets = data.get('secrets', [])
        return {
            'success': True,
            'count': len(secrets),
            'note': 'Secret values are never exposed by the GitHub API — only names and timestamps are returned.',
            'secrets': [
                {'name': s['name'], 'created_at': s.get('created_at'), 'updated_at': s.get('updated_at')}
                for s in secrets
            ]
        }
    except Exception as e:
        logger.error(f"Error listing GitHub secrets: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_github_environments(
    repo_owner: str,
    repo_name: str,
    github_token: Optional[str] = None
) -> Dict[str, Any]:
    """List deployment environments configured in a GitHub repository."""
    try:
        tok = _get_github_token(github_token)
        resp = requests.get(
            f'https://api.github.com/repos/{repo_owner}/{repo_name}/environments',
            headers={'Authorization': f'Bearer {tok}', 'Accept': 'application/vnd.github+json'}
        )
        resp.raise_for_status()
        data = resp.json()
        envs = data.get('environments', [])
        return {
            'success': True,
            'count': len(envs),
            'environments': [
                {
                    'id': e['id'],
                    'name': e['name'],
                    'url': e.get('html_url'),
                    'protection_rules': [r.get('type') for r in e.get('protection_rules', [])],
                    'created_at': e.get('created_at'),
                    'updated_at': e.get('updated_at'),
                }
                for e in envs
            ]
        }
    except Exception as e:
        logger.error(f"Error listing GitHub environments: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def get_github_workflow_usage(
    repo_owner: str,
    repo_name: str,
    workflow_id: str,
    github_token: Optional[str] = None
) -> Dict[str, Any]:
    """Get billable minutes and run totals for a GitHub Actions workflow."""
    try:
        tok = _get_github_token(github_token)
        resp = requests.get(
            f'https://api.github.com/repos/{repo_owner}/{repo_name}/actions/workflows/{workflow_id}/timing',
            headers={'Authorization': f'Bearer {tok}', 'Accept': 'application/vnd.github+json'}
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            'success': True,
            'workflow_id': workflow_id,
            'billable': data.get('billable', {}),
        }
    except Exception as e:
        logger.error(f"Error getting workflow usage: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def get_tools() -> List[Dict[str, Any]]:
    """
    Get CI/CD tool definitions.

    Returns:
        List of tool definitions
    """
    jenkins_creds = {
        'jenkins_url': {'type': 'string', 'description': 'Jenkins server URL (overrides JENKINS_URL env var)'},
        'username': {'type': 'string', 'description': 'Jenkins username (overrides JENKINS_USERNAME env var)'},
        'token': {'type': 'string', 'description': 'Jenkins API token (overrides JENKINS_TOKEN env var)'},
    }
    gh_creds = {
        'repo_owner': {'type': 'string', 'description': 'Repository owner (user or org)'},
        'repo_name': {'type': 'string', 'description': 'Repository name'},
        'github_token': {'type': 'string', 'description': 'GitHub personal access token (overrides GITHUB_TOKEN env var)'},
    }
    return [
        {
            'name': 'trigger_jenkins_job',
            'description': 'Trigger a Jenkins job with optional parameters',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'job_name': {
                        'type': 'string',
                        'description': 'Name of the Jenkins job'
                    },
                    'parameters': {
                        'type': 'object',
                        'description': 'Dictionary of job parameters'
                    },
                    'jenkins_url': {
                        'type': 'string',
                        'description': 'Jenkins server URL'
                    },
                    'username': {
                        'type': 'string',
                        'description': 'Jenkins username'
                    },
                    'token': {
                        'type': 'string',
                        'description': 'Jenkins API token'
                    }
                },
                'required': ['job_name']
            },
            'handler': trigger_jenkins_job
        },
        {
            'name': 'get_jenkins_job_status',
            'description': 'Get status of a Jenkins job or specific build',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'job_name': {
                        'type': 'string',
                        'description': 'Name of the Jenkins job'
                    },
                    'build_number': {
                        'type': 'integer',
                        'description': 'Specific build number (gets last build if not specified)'
                    },
                    'jenkins_url': {
                        'type': 'string',
                        'description': 'Jenkins server URL'
                    },
                    'username': {
                        'type': 'string',
                        'description': 'Jenkins username'
                    },
                    'token': {
                        'type': 'string',
                        'description': 'Jenkins API token'
                    }
                },
                'required': ['job_name']
            },
            'handler': get_jenkins_job_status
        },
        {
            'name': 'get_jenkins_build_logs',
            'description': 'Get console logs from a Jenkins build',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'job_name': {
                        'type': 'string',
                        'description': 'Name of the Jenkins job'
                    },
                    'build_number': {
                        'type': 'integer',
                        'description': 'Build number'
                    },
                    'jenkins_url': {
                        'type': 'string',
                        'description': 'Jenkins server URL'
                    },
                    'username': {
                        'type': 'string',
                        'description': 'Jenkins username'
                    },
                    'token': {
                        'type': 'string',
                        'description': 'Jenkins API token'
                    }
                },
                'required': ['job_name', 'build_number']
            },
            'handler': get_jenkins_build_logs
        },
        {
            'name': 'trigger_github_workflow',
            'description': 'Trigger a GitHub Actions workflow',
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
                    'workflow_name': {
                        'type': 'string',
                        'description': 'Workflow filename (e.g., deploy.yml)'
                    },
                    'ref': {
                        'type': 'string',
                        'description': 'Git ref (branch, tag, or commit)',
                        'default': 'main'
                    },
                    'inputs': {
                        'type': 'object',
                        'description': 'Workflow input parameters'
                    },
                    'github_token': {
                        'type': 'string',
                        'description': 'GitHub personal access token'
                    }
                },
                'required': ['repo_owner', 'repo_name', 'workflow_name']
            },
            'handler': trigger_github_workflow
        },
        {
            'name': 'get_github_workflow_runs',
            'description': 'Get GitHub Actions workflow runs with optional filtering',
            'input_schema': {
                'type': 'object',
                'properties': {
                    **gh_creds,
                    'workflow_name': {'type': 'string', 'description': 'Filter by workflow name'},
                    'status': {'type': 'string', 'enum': ['queued', 'in_progress', 'completed'], 'description': 'Filter by status'},
                },
                'required': ['repo_owner', 'repo_name']
            },
            'handler': get_github_workflow_runs
        },
        # --- new Jenkins tools ---
        {
            'name': 'list_jenkins_jobs',
            'description': 'List all Jenkins jobs with their current status (color)',
            'input_schema': {'type': 'object', 'properties': {**jenkins_creds}, 'required': []},
            'handler': list_jenkins_jobs
        },
        {
            'name': 'get_jenkins_queue',
            'description': 'Get the Jenkins build queue — jobs waiting to be executed',
            'input_schema': {'type': 'object', 'properties': {**jenkins_creds}, 'required': []},
            'handler': get_jenkins_queue
        },
        {
            'name': 'abort_jenkins_build',
            'description': 'Abort a currently running Jenkins build',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'job_name': {'type': 'string', 'description': 'Name of the Jenkins job'},
                    'build_number': {'type': 'integer', 'description': 'Build number to abort'},
                    **jenkins_creds,
                },
                'required': ['job_name', 'build_number']
            },
            'handler': abort_jenkins_build
        },
        {
            'name': 'enable_jenkins_job',
            'description': 'Enable a disabled Jenkins job so it can be triggered again',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'job_name': {'type': 'string', 'description': 'Name of the Jenkins job'},
                    **jenkins_creds,
                },
                'required': ['job_name']
            },
            'handler': enable_jenkins_job
        },
        {
            'name': 'disable_jenkins_job',
            'description': 'Disable a Jenkins job to prevent it from being triggered (does not delete it)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'job_name': {'type': 'string', 'description': 'Name of the Jenkins job'},
                    **jenkins_creds,
                },
                'required': ['job_name']
            },
            'handler': disable_jenkins_job
        },
        {
            'name': 'get_jenkins_job_config',
            'description': 'Get the XML configuration (config.xml / Jenkinsfile) of a Jenkins job',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'job_name': {'type': 'string', 'description': 'Name of the Jenkins job'},
                    **jenkins_creds,
                },
                'required': ['job_name']
            },
            'handler': get_jenkins_job_config
        },
        {
            'name': 'list_jenkins_nodes',
            'description': 'List all Jenkins build agents (nodes) and their online/offline status',
            'input_schema': {'type': 'object', 'properties': {**jenkins_creds}, 'required': []},
            'handler': list_jenkins_nodes
        },
        {
            'name': 'delete_jenkins_build',
            'description': 'Delete a specific build record from Jenkins build history',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'job_name': {'type': 'string', 'description': 'Name of the Jenkins job'},
                    'build_number': {'type': 'integer', 'description': 'Build number to delete'},
                    **jenkins_creds,
                },
                'required': ['job_name', 'build_number']
            },
            'handler': delete_jenkins_build
        },
        # --- new GitHub Actions tools ---
        {
            'name': 'list_github_workflows',
            'description': 'List all GitHub Actions workflow definitions in a repository',
            'input_schema': {'type': 'object', 'properties': {**gh_creds}, 'required': ['repo_owner', 'repo_name']},
            'handler': list_github_workflows
        },
        {
            'name': 'get_github_workflow_run',
            'description': 'Get details and status of a specific GitHub Actions workflow run by run ID',
            'input_schema': {
                'type': 'object',
                'properties': {
                    **gh_creds,
                    'run_id': {'type': 'integer', 'description': 'Workflow run ID'},
                },
                'required': ['repo_owner', 'repo_name', 'run_id']
            },
            'handler': get_github_workflow_run
        },
        {
            'name': 'cancel_github_workflow_run',
            'description': 'Cancel an in-progress GitHub Actions workflow run',
            'input_schema': {
                'type': 'object',
                'properties': {
                    **gh_creds,
                    'run_id': {'type': 'integer', 'description': 'Workflow run ID to cancel'},
                },
                'required': ['repo_owner', 'repo_name', 'run_id']
            },
            'handler': cancel_github_workflow_run
        },
        {
            'name': 'rerun_failed_github_jobs',
            'description': 'Re-run only the failed jobs in a completed GitHub Actions workflow run',
            'input_schema': {
                'type': 'object',
                'properties': {
                    **gh_creds,
                    'run_id': {'type': 'integer', 'description': 'Workflow run ID whose failed jobs to re-run'},
                },
                'required': ['repo_owner', 'repo_name', 'run_id']
            },
            'handler': rerun_failed_github_jobs
        },
        {
            'name': 'list_github_runners',
            'description': 'List self-hosted runners registered to a GitHub repository',
            'input_schema': {'type': 'object', 'properties': {**gh_creds}, 'required': ['repo_owner', 'repo_name']},
            'handler': list_github_runners
        },
        {
            'name': 'list_github_secrets',
            'description': 'List GitHub Actions secret names in a repository (values are never exposed)',
            'input_schema': {'type': 'object', 'properties': {**gh_creds}, 'required': ['repo_owner', 'repo_name']},
            'handler': list_github_secrets
        },
        {
            'name': 'list_github_environments',
            'description': 'List deployment environments configured in a GitHub repository',
            'input_schema': {'type': 'object', 'properties': {**gh_creds}, 'required': ['repo_owner', 'repo_name']},
            'handler': list_github_environments
        },
        {
            'name': 'get_github_workflow_usage',
            'description': 'Get billable minutes and run totals for a GitHub Actions workflow',
            'input_schema': {
                'type': 'object',
                'properties': {
                    **gh_creds,
                    'workflow_id': {'type': 'string', 'description': 'Workflow ID or filename (e.g. deploy.yml)'},
                },
                'required': ['repo_owner', 'repo_name', 'workflow_id']
            },
            'handler': get_github_workflow_usage
        },
    ]
