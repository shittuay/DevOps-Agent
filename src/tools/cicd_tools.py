"""CI/CD pipeline integration tools for DevOps Agent."""
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


def get_tools() -> List[Dict[str, Any]]:
    """
    Get CI/CD tool definitions.

    Returns:
        List of tool definitions
    """
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
                        'description': 'Filter by workflow name'
                    },
                    'status': {
                        'type': 'string',
                        'enum': ['queued', 'in_progress', 'completed'],
                        'description': 'Filter by status'
                    },
                    'github_token': {
                        'type': 'string',
                        'description': 'GitHub personal access token'
                    }
                },
                'required': ['repo_owner', 'repo_name']
            },
            'handler': get_github_workflow_runs
        }
    ]
