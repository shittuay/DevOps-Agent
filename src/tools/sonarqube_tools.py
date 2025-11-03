"""SonarQube tools for DevOps Agent."""
import requests
from typing import Dict, Any, Optional, List
from ..utils import get_logger

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
    """
    Get security hotspots for a project.

    Args:
        base_url: SonarQube server URL
        project_key: Project key
        token: Authentication token
        status: Filter by status (TO_REVIEW, REVIEWED)

    Returns:
        Dictionary with hotspots
    """
    try:
        url, headers = _get_sonar_client(base_url, token)

        params = {'projectKey': project_key}
        if status:
            params['status'] = status

        response = requests.get(
            f'{url}/api/hotspots/search',
            headers=headers,
            params=params,
            timeout=30
        )
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
