"""Nexus Repository Manager tools for DevOps Agent."""
import requests
from typing import Dict, Any, Optional, List
from ..utils import get_logger, assert_safe_url, safe_request

logger = get_logger(__name__)


def _get_nexus_client(
    base_url: str,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> tuple:
    """
    Returns (base_url, auth_tuple) from explicit args or the requesting user's saved Nexus.
    Auth: Basic auth with username/password against Nexus REST API v1.
    """
    from .integration_auth import credentials
    creds = credentials('nexus', caller_url=base_url, username=username, password=password)
    url = creds['url'].rstrip('/')
    assert_safe_url(url)
    return url, (creds['username'], creds['password'])


def nexus_get_system_status(
    base_url: str,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> Dict[str, Any]:
    """Check Nexus system health and version information."""
    try:
        url, auth = _get_nexus_client(base_url, username, password)
        response = safe_request('GET', f'{url}/service/rest/v1/status', auth=auth, timeout=15)
        if response.status_code == 200:
            return {'success': True, 'status': 'healthy', 'message': 'Nexus is running and healthy'}
        # Try /status/check for more detail
        check = safe_request('GET', f'{url}/service/rest/v1/status/check', auth=auth, timeout=15)
        check.raise_for_status()
        return {'success': True, 'status': 'healthy', 'checks': check.json()}
    except Exception as e:
        logger.error(f"Error checking Nexus status: {str(e)}")
        return {'success': False, 'error': str(e)}


def nexus_list_repositories(
    base_url: str,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> Dict[str, Any]:
    """List all repositories in Nexus (hosted, proxy, and group)."""
    try:
        url, auth = _get_nexus_client(base_url, username, password)
        response = safe_request('GET', f'{url}/service/rest/v1/repositories', auth=auth, timeout=30)
        response.raise_for_status()
        repos = response.json()
        return {
            'success': True,
            'count': len(repos),
            'repositories': [
                {
                    'name': r.get('name'),
                    'format': r.get('format'),
                    'type': r.get('type'),   # hosted | proxy | group
                    'url': r.get('url'),
                    'online': r.get('online', True),
                }
                for r in repos
            ]
        }
    except Exception as e:
        logger.error(f"Error listing Nexus repositories: {str(e)}")
        return {'success': False, 'error': str(e)}


def nexus_get_repository(
    base_url: str,
    repository_name: str,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> Dict[str, Any]:
    """Get configuration details for a specific Nexus repository."""
    try:
        url, auth = _get_nexus_client(base_url, username, password)
        response = safe_request('GET', 
            f'{url}/service/rest/v1/repositories/{repository_name}',
            auth=auth,
            timeout=30
        )
        response.raise_for_status()
        return {'success': True, 'repository': response.json()}
    except Exception as e:
        logger.error(f"Error getting Nexus repository: {str(e)}")
        return {'success': False, 'error': str(e)}


def nexus_create_repository(
    base_url: str,
    repository_name: str,
    format: str,
    type: str,
    blob_store: str = 'default',
    strict_content_validation: bool = True,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new Nexus repository.
    format: maven2 | npm | docker | pypi | raw | helm | go | nuget | yum | apt
    type: hosted | proxy | group
    """
    try:
        url, auth = _get_nexus_client(base_url, username, password)
        payload = {
            'name': repository_name,
            'online': True,
            'storage': {
                'blobStoreName': blob_store,
                'strictContentTypeValidation': strict_content_validation,
                'writePolicy': 'allow_once'
            }
        }
        # Maven hosted needs layoutPolicy
        if format == 'maven2':
            payload['maven'] = {'versionPolicy': 'MIXED', 'layoutPolicy': 'STRICT'}

        response = safe_request('POST', 
            f'{url}/service/rest/v1/repositories/{format}/{type}',
            auth=auth,
            json=payload,
            timeout=30
        )
        if response.status_code in (200, 201, 204):
            return {
                'success': True,
                'message': f'Repository "{repository_name}" ({format}/{type}) created successfully',
                'name': repository_name,
                'format': format,
                'type': type
            }
        return {'success': False, 'error': f'HTTP {response.status_code}: {response.text}'}
    except Exception as e:
        logger.error(f"Error creating Nexus repository: {str(e)}")
        return {'success': False, 'error': str(e)}


def nexus_delete_repository(
    base_url: str,
    repository_name: str,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> Dict[str, Any]:
    """
    Permanently delete a Nexus repository and all its artifacts.
    WARNING: Deleting a hosted repository removes all stored artifacts. This cannot be undone.
    Proxy and group repositories can be recreated; hosted repositories cannot.
    """
    try:
        url, auth = _get_nexus_client(base_url, username, password)
        response = safe_request('DELETE', 
            f'{url}/service/rest/v1/repositories/{repository_name}',
            auth=auth,
            timeout=30
        )
        if response.status_code in (200, 204):
            return {
                'success': True,
                'message': f'Repository "{repository_name}" deleted permanently',
                'warning': 'All artifacts stored in this hosted repository have been removed and cannot be recovered.'
            }
        return {'success': False, 'error': f'HTTP {response.status_code}: {response.text}'}
    except Exception as e:
        logger.error(f"Error deleting Nexus repository: {str(e)}")
        return {'success': False, 'error': str(e)}


def nexus_search_components(
    base_url: str,
    repository: Optional[str] = None,
    group: Optional[str] = None,
    name: Optional[str] = None,
    version: Optional[str] = None,
    format: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> Dict[str, Any]:
    """
    Search for components (artifacts) across Nexus repositories.
    For Maven: group=groupId, name=artifactId.
    Returns up to 50 results (first page).
    """
    try:
        url, auth = _get_nexus_client(base_url, username, password)
        params = {}
        if repository:
            params['repository'] = repository
        if group:
            params['group'] = group
        if name:
            params['name'] = name
        if version:
            params['version'] = version
        if format:
            params['format'] = format

        response = safe_request('GET', 
            f'{url}/service/rest/v1/search',
            auth=auth,
            params=params,
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        items = data.get('items', [])
        return {
            'success': True,
            'count': len(items),
            'continuation_token': data.get('continuationToken'),
            'components': [
                {
                    'id': c.get('id'),
                    'repository': c.get('repository'),
                    'format': c.get('format'),
                    'group': c.get('group'),
                    'name': c.get('name'),
                    'version': c.get('version'),
                    'assets': [{'path': a.get('path'), 'size': a.get('fileSize')} for a in c.get('assets', [])]
                }
                for c in items
            ]
        }
    except Exception as e:
        logger.error(f"Error searching Nexus components: {str(e)}")
        return {'success': False, 'error': str(e)}


def nexus_get_component(
    base_url: str,
    component_id: str,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> Dict[str, Any]:
    """Get details for a specific component by its Nexus component ID."""
    try:
        url, auth = _get_nexus_client(base_url, username, password)
        response = safe_request('GET', 
            f'{url}/service/rest/v1/components/{component_id}',
            auth=auth,
            timeout=30
        )
        response.raise_for_status()
        return {'success': True, 'component': response.json()}
    except Exception as e:
        logger.error(f"Error getting Nexus component: {str(e)}")
        return {'success': False, 'error': str(e)}


def nexus_delete_component(
    base_url: str,
    component_id: str,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a specific component (and all its assets) from Nexus by component ID."""
    try:
        url, auth = _get_nexus_client(base_url, username, password)
        response = safe_request('DELETE', 
            f'{url}/service/rest/v1/components/{component_id}',
            auth=auth,
            timeout=30
        )
        if response.status_code in (200, 204):
            return {
                'success': True,
                'message': f'Component {component_id} deleted successfully',
                'component_id': component_id
            }
        return {'success': False, 'error': f'HTTP {response.status_code}: {response.text}'}
    except Exception as e:
        logger.error(f"Error deleting Nexus component: {str(e)}")
        return {'success': False, 'error': str(e)}


def nexus_list_assets(
    base_url: str,
    repository: str,
    continuation_token: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> Dict[str, Any]:
    """
    List assets (individual files) in a repository.
    Use continuation_token from a previous response to get the next page.
    """
    try:
        url, auth = _get_nexus_client(base_url, username, password)
        params = {'repository': repository}
        if continuation_token:
            params['continuationToken'] = continuation_token
        response = safe_request('GET', f'{url}/service/rest/v1/assets', auth=auth, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        items = data.get('items', [])
        return {
            'success': True,
            'repository': repository,
            'count': len(items),
            'continuation_token': data.get('continuationToken'),
            'assets': [
                {
                    'id': a.get('id'),
                    'path': a.get('path'),
                    'repository': a.get('repository'),
                    'format': a.get('format'),
                    'size': a.get('fileSize'),
                    'content_type': a.get('contentType'),
                    'last_modified': a.get('lastModified'),
                    'checksum_sha1': a.get('checksum', {}).get('sha1'),
                }
                for a in items
            ]
        }
    except Exception as e:
        logger.error(f"Error listing Nexus assets: {str(e)}")
        return {'success': False, 'error': str(e)}


def nexus_delete_asset(
    base_url: str,
    asset_id: str,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a specific asset (file) from Nexus by asset ID."""
    try:
        url, auth = _get_nexus_client(base_url, username, password)
        response = safe_request('DELETE', 
            f'{url}/service/rest/v1/assets/{asset_id}',
            auth=auth,
            timeout=30
        )
        if response.status_code in (200, 204):
            return {'success': True, 'message': f'Asset {asset_id} deleted', 'asset_id': asset_id}
        return {'success': False, 'error': f'HTTP {response.status_code}: {response.text}'}
    except Exception as e:
        logger.error(f"Error deleting Nexus asset: {str(e)}")
        return {'success': False, 'error': str(e)}


def nexus_list_users(
    base_url: str,
    source: str = 'default',
    username: Optional[str] = None,
    password: Optional[str] = None
) -> Dict[str, Any]:
    """List Nexus users. source='default' for local users, 'LDAP' for LDAP-sourced users."""
    try:
        url, auth = _get_nexus_client(base_url, username, password)
        response = safe_request('GET', 
            f'{url}/service/rest/v1/security/users',
            auth=auth,
            params={'source': source},
            timeout=30
        )
        response.raise_for_status()
        users = response.json()
        return {
            'success': True,
            'count': len(users),
            'users': [
                {
                    'userId': u.get('userId'),
                    'firstName': u.get('firstName'),
                    'lastName': u.get('lastName'),
                    'emailAddress': u.get('emailAddress'),
                    'status': u.get('status'),
                    'roles': u.get('roles', []),
                }
                for u in users
            ]
        }
    except Exception as e:
        logger.error(f"Error listing Nexus users: {str(e)}")
        return {'success': False, 'error': str(e)}


def nexus_run_cleanup_task(
    base_url: str,
    task_name: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> Dict[str, Any]:
    """
    Run a Nexus scheduled task (e.g. cleanup policies, compact blob store).
    Lists available tasks if task_name is not specified, then triggers the matching task.
    """
    try:
        url, auth = _get_nexus_client(base_url, username, password)
        # List all tasks to find the target
        tasks_resp = safe_request('GET', f'{url}/service/rest/v1/tasks', auth=auth, timeout=30)
        tasks_resp.raise_for_status()
        tasks = tasks_resp.json().get('items', [])

        if not task_name:
            return {
                'success': True,
                'message': 'No task_name specified — listing available tasks',
                'tasks': [{'id': t.get('id'), 'name': t.get('name'), 'type': t.get('type'),
                           'lastRunResult': t.get('lastRunResult'), 'nextRun': t.get('nextRun')}
                          for t in tasks]
            }

        task = next((t for t in tasks if t.get('name') == task_name), None)
        if not task:
            available = [t.get('name') for t in tasks]
            return {'success': False, 'error': f'Task "{task_name}" not found. Available: {available}'}

        run_resp = safe_request('POST', 
            f'{url}/service/rest/v1/tasks/{task["id"]}/run',
            auth=auth,
            timeout=30
        )
        if run_resp.status_code in (200, 204):
            return {
                'success': True,
                'message': f'Task "{task_name}" triggered successfully',
                'task_id': task['id'],
                'task_type': task.get('type')
            }
        return {'success': False, 'error': f'HTTP {run_resp.status_code}: {run_resp.text}'}
    except Exception as e:
        logger.error(f"Error running Nexus task: {str(e)}")
        return {'success': False, 'error': str(e)}


# ==================== TOOL REGISTRATION ====================

def get_tools() -> List[Dict[str, Any]]:
    """Get all Nexus Repository Manager tool definitions."""
    return [
        {
            'name': 'nexus_get_system_status',
            'description': 'Check Nexus Repository Manager health and confirm it is running.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'Nexus server URL (e.g. https://nexus.company.com)'},
                    'username': {'type': 'string', 'description': "Nexus username (omit to use the user's connected Nexus)"},
                    'password': {'type': 'string', 'description': "Nexus password (omit to use the user's connected Nexus)"}
                },
                'required': ['base_url']
            },
            'handler': nexus_get_system_status
        },
        {
            'name': 'nexus_list_repositories',
            'description': 'List all Nexus repositories (hosted, proxy, group) with their format and URL.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'Nexus server URL'},
                    'username': {'type': 'string', 'description': 'Nexus username'},
                    'password': {'type': 'string', 'description': 'Nexus password'}
                },
                'required': ['base_url']
            },
            'handler': nexus_list_repositories
        },
        {
            'name': 'nexus_get_repository',
            'description': 'Get full configuration of a specific Nexus repository by name.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'Nexus server URL'},
                    'repository_name': {'type': 'string', 'description': 'Repository name'},
                    'username': {'type': 'string', 'description': 'Nexus username'},
                    'password': {'type': 'string', 'description': 'Nexus password'}
                },
                'required': ['base_url', 'repository_name']
            },
            'handler': nexus_get_repository
        },
        {
            'name': 'nexus_create_repository',
            'description': 'Create a new Nexus repository. Supports formats: maven2, npm, docker, pypi, raw, helm, go, nuget. Types: hosted, proxy, group.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'Nexus server URL'},
                    'repository_name': {'type': 'string', 'description': 'Name for the new repository'},
                    'format': {'type': 'string', 'description': 'Repository format: maven2, npm, docker, pypi, raw, helm, go, nuget, yum, apt'},
                    'type': {'type': 'string', 'enum': ['hosted', 'proxy', 'group'], 'description': 'Repository type'},
                    'blob_store': {'type': 'string', 'description': 'Blob store name', 'default': 'default'},
                    'strict_content_validation': {'type': 'boolean', 'default': True, 'description': 'Validate content type on upload'},
                    'username': {'type': 'string', 'description': 'Nexus username'},
                    'password': {'type': 'string', 'description': 'Nexus password'}
                },
                'required': ['base_url', 'repository_name', 'format', 'type']
            },
            'handler': nexus_create_repository
        },
        {
            'name': 'nexus_delete_repository',
            'description': 'Permanently delete a Nexus repository. WARNING: Deleting a hosted repository removes ALL stored artifacts and cannot be undone.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'Nexus server URL'},
                    'repository_name': {'type': 'string', 'description': 'Name of the repository to delete'},
                    'username': {'type': 'string', 'description': 'Nexus username'},
                    'password': {'type': 'string', 'description': 'Nexus password'}
                },
                'required': ['base_url', 'repository_name']
            },
            'handler': nexus_delete_repository
        },
        {
            'name': 'nexus_search_components',
            'description': 'Search for components (artifacts) in Nexus by repository, group, name, and version. For Maven: group=groupId, name=artifactId.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'Nexus server URL'},
                    'repository': {'type': 'string', 'description': 'Filter by repository name'},
                    'group': {'type': 'string', 'description': 'Filter by group (Maven groupId or npm scope)'},
                    'name': {'type': 'string', 'description': 'Filter by component name (Maven artifactId)'},
                    'version': {'type': 'string', 'description': 'Filter by version'},
                    'format': {'type': 'string', 'description': 'Filter by format (maven2, npm, docker, etc.)'},
                    'username': {'type': 'string', 'description': 'Nexus username'},
                    'password': {'type': 'string', 'description': 'Nexus password'}
                },
                'required': ['base_url']
            },
            'handler': nexus_search_components
        },
        {
            'name': 'nexus_get_component',
            'description': 'Get full details of a specific component by its Nexus component ID.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'Nexus server URL'},
                    'component_id': {'type': 'string', 'description': 'Nexus component ID'},
                    'username': {'type': 'string', 'description': 'Nexus username'},
                    'password': {'type': 'string', 'description': 'Nexus password'}
                },
                'required': ['base_url', 'component_id']
            },
            'handler': nexus_get_component
        },
        {
            'name': 'nexus_delete_component',
            'description': 'Delete a specific component and all its assets from Nexus by component ID.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'Nexus server URL'},
                    'component_id': {'type': 'string', 'description': 'Nexus component ID to delete'},
                    'username': {'type': 'string', 'description': 'Nexus username'},
                    'password': {'type': 'string', 'description': 'Nexus password'}
                },
                'required': ['base_url', 'component_id']
            },
            'handler': nexus_delete_component
        },
        {
            'name': 'nexus_list_assets',
            'description': 'List individual asset files in a Nexus repository. Supports pagination via continuation_token.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'Nexus server URL'},
                    'repository': {'type': 'string', 'description': 'Repository name to list assets from'},
                    'continuation_token': {'type': 'string', 'description': 'Token from previous response for next page'},
                    'username': {'type': 'string', 'description': 'Nexus username'},
                    'password': {'type': 'string', 'description': 'Nexus password'}
                },
                'required': ['base_url', 'repository']
            },
            'handler': nexus_list_assets
        },
        {
            'name': 'nexus_delete_asset',
            'description': 'Delete a specific asset (file) from Nexus by asset ID.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'Nexus server URL'},
                    'asset_id': {'type': 'string', 'description': 'Nexus asset ID to delete'},
                    'username': {'type': 'string', 'description': 'Nexus username'},
                    'password': {'type': 'string', 'description': 'Nexus password'}
                },
                'required': ['base_url', 'asset_id']
            },
            'handler': nexus_delete_asset
        },
        {
            'name': 'nexus_list_users',
            'description': 'List Nexus users. Specify source="LDAP" for LDAP-synced users.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'Nexus server URL'},
                    'source': {'type': 'string', 'description': 'User source: default (local) or LDAP', 'default': 'default'},
                    'username': {'type': 'string', 'description': 'Nexus admin username'},
                    'password': {'type': 'string', 'description': 'Nexus admin password'}
                },
                'required': ['base_url']
            },
            'handler': nexus_list_users
        },
        {
            'name': 'nexus_run_cleanup_task',
            'description': 'List or run a Nexus scheduled task (cleanup policies, compact blob store, etc.). Omit task_name to see available tasks.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'base_url': {'type': 'string', 'description': 'Nexus server URL'},
                    'task_name': {'type': 'string', 'description': 'Task name to run. Omit to list all available tasks.'},
                    'username': {'type': 'string', 'description': 'Nexus username'},
                    'password': {'type': 'string', 'description': 'Nexus password'}
                },
                'required': ['base_url']
            },
            'handler': nexus_run_cleanup_task
        },
    ]
