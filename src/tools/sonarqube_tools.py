"""SonarQube tools for DevOps Agent."""
import requests
from typing import Dict, Any, Optional, List
from ..utils import get_logger, assert_safe_url

logger = get_logger(__name__)


def _get_sonar_client(base_url: str, token: Optional[str] = None):
    """
    Get SonarQube client configuration.

    Args:
        base_url: SonarQube server URL
        token: Authentication token

    Returns:
        Tuple of (base_url, headers)
    """
    import os

    assert_safe_url(base_url)

    if not token:
        token = os.environ.get('SONAR_TOKEN')
        if not token:
            raise Exception("SONAR_TOKEN not found in environment variables")

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

    return base_url.rstrip('/'), headers


def get_sonar_projects(
    base_url: str,
    token: Optional[str] = None,
    page_size: int = 100
) -> Dict[str, Any]:
    """
    Get list of SonarQube projects.

    Args:
        base_url: SonarQube server URL
        token: Authentication token
        page_size: Number of projects per page

    Returns:
        Dictionary with projects
    """
    try:
        url, headers = _get_sonar_client(base_url, token)

        response = requests.get(
            f'{url}/api/projects/search',
            headers=headers,
            params={'ps': page_size},
            timeout=30
        )
        response.raise_for_status()

        data = response.json()

        projects = []
        for project in data.get('components', []):
            projects.append({
                'key': project.get('key'),
                'name': project.get('name'),
                'qualifier': project.get('qualifier'),
                'visibility': project.get('visibility'),
                'last_analysis_date': project.get('lastAnalysisDate')
            })

        return {
            'success': True,
            'count': len(projects),
            'total': data.get('paging', {}).get('total', 0),
            'projects': projects
        }
    except Exception as e:
        logger.error(f"Error getting SonarQube projects: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_sonar_project_quality(
    base_url: str,
    project_key: str,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get quality gate status for a project.

    Args:
        base_url: SonarQube server URL
        project_key: Project key
        token: Authentication token

    Returns:
        Dictionary with quality gate status
    """
    try:
        url, headers = _get_sonar_client(base_url, token)

        response = requests.get(
            f'{url}/api/qualitygates/project_status',
            headers=headers,
            params={'projectKey': project_key},
            timeout=30
        )
        response.raise_for_status()

        data = response.json()
        project_status = data.get('projectStatus', {})

        return {
            'success': True,
            'project_key': project_key,
            'status': project_status.get('status'),
            'conditions': project_status.get('conditions', []),
            'caycStatus': project_status.get('caycStatus')
        }
    except Exception as e:
        logger.error(f"Error getting project quality: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_sonar_measures(
    base_url: str,
    project_key: str,
    metrics: List[str],
    token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get measures for a project.

    Args:
        base_url: SonarQube server URL
        project_key: Project key
        metrics: List of metric keys
        token: Authentication token

    Returns:
        Dictionary with measures
    """
    try:
        url, headers = _get_sonar_client(base_url, token)

        # Common metrics if none specified
        if not metrics:
            metrics = [
                'bugs', 'vulnerabilities', 'code_smells',
                'coverage', 'duplicated_lines_density',
                'ncloc', 'sqale_rating', 'reliability_rating',
                'security_rating'
            ]

        response = requests.get(
            f'{url}/api/measures/component',
            headers=headers,
            params={
                'component': project_key,
                'metricKeys': ','.join(metrics)
            },
            timeout=30
        )
        response.raise_for_status()

        data = response.json()
        component = data.get('component', {})

        measures = {}
        for measure in component.get('measures', []):
            measures[measure['metric']] = measure.get('value', measure.get('periods', [{}])[0].get('value'))

        return {
            'success': True,
            'project_key': project_key,
            'measures': measures
        }
    except Exception as e:
        logger.error(f"Error getting measures: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_sonar_issues(
    base_url: str,
    project_key: str,
    token: Optional[str] = None,
    severities: Optional[List[str]] = None,
    types: Optional[List[str]] = None,
    page_size: int = 100
) -> Dict[str, Any]:
    """
    Get issues for a project.

    Args:
        base_url: SonarQube server URL
        project_key: Project key
        token: Authentication token
        severities: Filter by severities (BLOCKER, CRITICAL, MAJOR, MINOR, INFO)
        types: Filter by types (BUG, VULNERABILITY, CODE_SMELL)
        page_size: Number of issues per page

    Returns:
        Dictionary with issues
    """
    try:
        url, headers = _get_sonar_client(base_url, token)

        params = {
            'componentKeys': project_key,
            'ps': page_size
        }

        if severities:
            params['severities'] = ','.join(severities)
        if types:
            params['types'] = ','.join(types)

        response = requests.get(
            f'{url}/api/issues/search',
            headers=headers,
            params=params,
            timeout=30
        )
        response.raise_for_status()

        data = response.json()

        issues = []
        for issue in data.get('issues', []):
            issues.append({
                'key': issue.get('key'),
                'rule': issue.get('rule'),
                'severity': issue.get('severity'),
                'type': issue.get('type'),
                'component': issue.get('component'),
                'message': issue.get('message'),
                'line': issue.get('line'),
                'status': issue.get('status'),
                'effort': issue.get('effort'),
                'debt': issue.get('debt'),
                'creationDate': issue.get('creationDate')
            })

        return {
            'success': True,
            'project_key': project_key,
            'count': len(issues),
            'total': data.get('total', 0),
            'issues': issues
        }
    except Exception as e:
        logger.error(f"Error getting issues: {str(e)}")
        return {'success': False, 'error': str(e)}


def trigger_sonar_analysis(
    base_url: str,
    project_key: str,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Trigger a new analysis for a project.

    Args:
        base_url: SonarQube server URL
        project_key: Project key
        token: Authentication token

    Returns:
        Dictionary with result
    """
    try:
        url, headers = _get_sonar_client(base_url, token)

        # Note: This typically requires scanner execution, not just an API call
        # This endpoint may vary by SonarQube version
        response = requests.post(
            f'{url}/api/ce/submit',
            headers=headers,
            params={'projectKey': project_key},
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            return {
                'success': True,
                'message': 'Analysis triggered',
                'task': data
            }
        else:
            return {
                'success': False,
                'message': 'Analysis trigger requires scanner execution',
                'note': 'Use sonar-scanner CLI tool to run analysis'
            }
    except Exception as e:
        logger.error(f"Error triggering analysis: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_sonar_hotspots(
    base_url: str,
    project_key: str,
    token: Optional[str] = None,
    status: Optional[str] = None
) -> Dict[str, Any]:
    """Get security hotspots for a project."""
    try:
        url, headers = _get_sonar_client(base_url, token)
        params = {'projectKey': project_key}
        if status:
            params['status'] = status
        response = requests.get(f'{url}/api/hotspots/search', headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        hotspots = []
        for hotspot in data.get('hotspots', []):
            hotspots.append({
                'key': hotspot.get('key'),
                'component': hotspot.get('component'),
                'message': hotspot.get('message'),
                'status': hotspot.get('status'),
                'vulnerabilityProbability': hotspot.get('vulnerabilityProbability'),
                'securityCategory': hotspot.get('securityCategory'),
                'line': hotspot.get('line'),
                'creationDate': hotspot.get('creationDate')
            })
        return {
            'success': True,
            'project_key': project_key,
            'count': len(hotspots),
            'total': data.get('paging', {}).get('total', 0),
            'hotspots': hotspots
        }
    except Exception as e:
        logger.error(f"Error getting hotspots: {str(e)}")
        return {'success': False, 'error': str(e)}


def create_sonar_project(
    base_url: str,
    project_key: str,
    project_name: str,
    visibility: str = 'private',
    token: Optional[str] = None
) -> Dict[str, Any]:
    """Create a new SonarQube project."""
    try:
        url, headers = _get_sonar_client(base_url, token)
        response = requests.post(
            f'{url}/api/projects/create',
            headers=headers,
            params={'project': project_key, 'name': project_name, 'visibility': visibility},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        return {
            'success': True,
            'message': f'Project "{project_name}" created successfully',
            'project': data.get('project', {})
        }
    except Exception as e:
        logger.error(f"Error creating SonarQube project: {str(e)}")
        return {'success': False, 'error': str(e)}


def delete_sonar_project(
    base_url: str,
    project_key: str,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a SonarQube project and all its data."""
    try:
        url, headers = _get_sonar_client(base_url, token)
        response = requests.post(
            f'{url}/api/projects/delete',
            headers=headers,
            params={'project': project_key},
            timeout=30
        )
        response.raise_for_status()
        return {
            'success': True,
            'message': f'Project "{project_key}" deleted successfully',
            'warning': 'All analysis history and issues for this project have been permanently removed.'
        }
    except Exception as e:
        logger.error(f"Error deleting SonarQube project: {str(e)}")
        return {'success': False, 'error': str(e)}


def update_sonar_issue(
    base_url: str,
    issue_key: str,
    status: str,
    comment: Optional[str] = None,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update the status of a SonarQube issue (e.g. mark as won't fix or false positive).
    Valid statuses: OPEN, CONFIRMED, RESOLVED, REOPENED, CLOSED.
    Use do_transition for: confirm, unconfirm, resolve, falsepositive, wontfix, reopen.
    """
    try:
        url, headers = _get_sonar_client(base_url, token)
        response = requests.post(
            f'{url}/api/issues/do_transition',
            headers=headers,
            params={'issue': issue_key, 'transition': status},
            timeout=30
        )
        response.raise_for_status()
        if comment:
            requests.post(
                f'{url}/api/issues/add_comment',
                headers=headers,
                params={'issue': issue_key, 'text': comment},
                timeout=30
            )
        return {
            'success': True,
            'message': f'Issue {issue_key} transitioned to {status}',
            'issue_key': issue_key,
            'transition': status
        }
    except Exception as e:
        logger.error(f"Error updating SonarQube issue: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_sonar_quality_gates(
    base_url: str,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """List all quality gates defined in SonarQube."""
    try:
        url, headers = _get_sonar_client(base_url, token)
        response = requests.get(f'{url}/api/qualitygates/list', headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        return {
            'success': True,
            'count': len(data.get('qualygates', data.get('qualitygates', []))),
            'quality_gates': data.get('qualygates', data.get('qualitygates', [])),
            'default': data.get('default')
        }
    except Exception as e:
        logger.error(f"Error listing quality gates: {str(e)}")
        return {'success': False, 'error': str(e)}


def assign_sonar_quality_gate(
    base_url: str,
    project_key: str,
    gate_name: str,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """Assign a quality gate to a project. The gate must exist in SonarQube."""
    try:
        url, headers = _get_sonar_client(base_url, token)
        # First resolve gate name to ID
        list_resp = requests.get(f'{url}/api/qualitygates/list', headers=headers, timeout=30)
        list_resp.raise_for_status()
        gates = list_resp.json().get('qualygates', list_resp.json().get('qualitygates', []))
        gate_id = next((g['id'] for g in gates if g.get('name') == gate_name), None)
        if not gate_id:
            return {'success': False, 'error': f'Quality gate "{gate_name}" not found'}
        response = requests.post(
            f'{url}/api/qualitygates/select',
            headers=headers,
            params={'projectKey': project_key, 'gateId': gate_id},
            timeout=30
        )
        response.raise_for_status()
        return {
            'success': True,
            'message': f'Quality gate "{gate_name}" assigned to project "{project_key}"',
            'project_key': project_key,
            'gate_name': gate_name
        }
    except Exception as e:
        logger.error(f"Error assigning quality gate: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_sonar_analysis_history(
    base_url: str,
    project_key: str,
    token: Optional[str] = None,
    page_size: int = 10
) -> Dict[str, Any]:
    """Get analysis history (past scans) for a project."""
    try:
        url, headers = _get_sonar_client(base_url, token)
        response = requests.get(
            f'{url}/api/project_analyses/search',
            headers=headers,
            params={'project': project_key, 'ps': page_size},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        analyses = []
        for a in data.get('analyses', []):
            analyses.append({
                'key': a.get('key'),
                'date': a.get('date'),
                'events': a.get('events', []),
                'projectVersion': a.get('projectVersion'),
                'buildString': a.get('buildString'),
            })
        return {
            'success': True,
            'project_key': project_key,
            'count': len(analyses),
            'analyses': analyses
        }
    except Exception as e:
        logger.error(f"Error getting analysis history: {str(e)}")
        return {'success': False, 'error': str(e)}


# ==================== TOOL REGISTRATION ====================

def get_tools() -> List[Dict[str, Any]]:
    """Get all SonarQube tool definitions."""
    return [
        {
            'name': 'get_sonar_projects',
            'description': 'List all SonarQube projects. Returns project keys, names, visibility, and last analysis date.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'SonarQube server URL (e.g. https://sonarqube.company.com)'},
                    'token': {'type': 'string', 'description': 'SonarQube authentication token (falls back to SONAR_TOKEN env var)'},
                    'page_size': {'type': 'integer', 'description': 'Number of projects per page', 'default': 100}
                },
                'required': ['base_url']
            },
            'handler': get_sonar_projects
        },
        {
            'name': 'get_sonar_project_quality',
            'description': 'Get quality gate status (PASSED/FAILED) for a SonarQube project.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'SonarQube server URL'},
                    'project_key': {'type': 'string', 'description': 'Project key (e.g. my-app)'},
                    'token': {'type': 'string', 'description': 'SonarQube authentication token'}
                },
                'required': ['base_url', 'project_key']
            },
            'handler': get_sonar_project_quality
        },
        {
            'name': 'get_sonar_measures',
            'description': 'Get code quality metrics for a project: bugs, vulnerabilities, code smells, coverage, duplication.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'SonarQube server URL'},
                    'project_key': {'type': 'string', 'description': 'Project key'},
                    'metrics': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Metric keys to fetch. Defaults to: bugs, vulnerabilities, code_smells, coverage, duplicated_lines_density, ncloc, sqale_rating, reliability_rating, security_rating'
                    },
                    'token': {'type': 'string', 'description': 'SonarQube authentication token'}
                },
                'required': ['base_url', 'project_key']
            },
            'handler': get_sonar_measures
        },
        {
            'name': 'get_sonar_issues',
            'description': 'Get bugs, vulnerabilities, and code smells for a project with optional severity and type filters.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'SonarQube server URL'},
                    'project_key': {'type': 'string', 'description': 'Project key'},
                    'token': {'type': 'string', 'description': 'SonarQube authentication token'},
                    'severities': {
                        'type': 'array',
                        'items': {'type': 'string', 'enum': ['BLOCKER', 'CRITICAL', 'MAJOR', 'MINOR', 'INFO']},
                        'description': 'Filter by severity levels'
                    },
                    'types': {
                        'type': 'array',
                        'items': {'type': 'string', 'enum': ['BUG', 'VULNERABILITY', 'CODE_SMELL']},
                        'description': 'Filter by issue types'
                    },
                    'page_size': {'type': 'integer', 'description': 'Number of issues per page', 'default': 100}
                },
                'required': ['base_url', 'project_key']
            },
            'handler': get_sonar_issues
        },
        {
            'name': 'trigger_sonar_analysis',
            'description': 'Attempt to trigger a SonarQube analysis. NOTE: Real analysis requires running sonar-scanner CLI in your CI pipeline — this API endpoint may not be supported on all versions.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'SonarQube server URL'},
                    'project_key': {'type': 'string', 'description': 'Project key'},
                    'token': {'type': 'string', 'description': 'SonarQube authentication token'}
                },
                'required': ['base_url', 'project_key']
            },
            'handler': trigger_sonar_analysis
        },
        {
            'name': 'get_sonar_hotspots',
            'description': 'Get security hotspots for a project — areas of code that may need security review.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'SonarQube server URL'},
                    'project_key': {'type': 'string', 'description': 'Project key'},
                    'token': {'type': 'string', 'description': 'SonarQube authentication token'},
                    'status': {'type': 'string', 'enum': ['TO_REVIEW', 'REVIEWED'], 'description': 'Filter by hotspot status'}
                },
                'required': ['base_url', 'project_key']
            },
            'handler': get_sonar_hotspots
        },
        {
            'name': 'create_sonar_project',
            'description': 'Create a new SonarQube project.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'SonarQube server URL'},
                    'project_key': {'type': 'string', 'description': 'Unique project key (e.g. my-app)'},
                    'project_name': {'type': 'string', 'description': 'Display name for the project'},
                    'visibility': {'type': 'string', 'enum': ['private', 'public'], 'default': 'private', 'description': 'Project visibility'},
                    'token': {'type': 'string', 'description': 'SonarQube authentication token'}
                },
                'required': ['base_url', 'project_key', 'project_name']
            },
            'handler': create_sonar_project
        },
        {
            'name': 'delete_sonar_project',
            'description': 'Permanently delete a SonarQube project and all its analysis history. This cannot be undone.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'SonarQube server URL'},
                    'project_key': {'type': 'string', 'description': 'Project key to delete'},
                    'token': {'type': 'string', 'description': 'SonarQube authentication token'}
                },
                'required': ['base_url', 'project_key']
            },
            'handler': delete_sonar_project
        },
        {
            'name': 'update_sonar_issue',
            'description': 'Transition a SonarQube issue status. Use transitions: confirm, unconfirm, resolve, falsepositive, wontfix, reopen.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'SonarQube server URL'},
                    'issue_key': {'type': 'string', 'description': 'Issue key (e.g. AXk9vW1Z...)'},
                    'status': {'type': 'string', 'description': 'Transition to apply: confirm, unconfirm, resolve, falsepositive, wontfix, reopen'},
                    'comment': {'type': 'string', 'description': 'Optional comment to add with the transition'},
                    'token': {'type': 'string', 'description': 'SonarQube authentication token'}
                },
                'required': ['base_url', 'issue_key', 'status']
            },
            'handler': update_sonar_issue
        },
        {
            'name': 'list_sonar_quality_gates',
            'description': 'List all quality gates defined in SonarQube, including which is the default.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'SonarQube server URL'},
                    'token': {'type': 'string', 'description': 'SonarQube authentication token'}
                },
                'required': ['base_url']
            },
            'handler': list_sonar_quality_gates
        },
        {
            'name': 'assign_sonar_quality_gate',
            'description': 'Assign a specific quality gate to a project by gate name.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'SonarQube server URL'},
                    'project_key': {'type': 'string', 'description': 'Project key'},
                    'gate_name': {'type': 'string', 'description': 'Name of the quality gate to assign'},
                    'token': {'type': 'string', 'description': 'SonarQube authentication token'}
                },
                'required': ['base_url', 'project_key', 'gate_name']
            },
            'handler': assign_sonar_quality_gate
        },
        {
            'name': 'get_sonar_analysis_history',
            'description': 'Get past analysis runs for a project, showing scan dates, versions, and events.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'SonarQube server URL'},
                    'project_key': {'type': 'string', 'description': 'Project key'},
                    'token': {'type': 'string', 'description': 'SonarQube authentication token'},
                    'page_size': {'type': 'integer', 'description': 'Number of analyses to return', 'default': 10}
                },
                'required': ['base_url', 'project_key']
            },
            'handler': get_sonar_analysis_history
        },
    ]
