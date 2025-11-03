"""Monitoring tools (Prometheus, Datadog, Grafana) for DevOps Agent."""
import requests
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from ..utils import get_logger

logger = get_logger(__name__)


# ============================================================================
# PROMETHEUS TOOLS
# ============================================================================

def query_prometheus(
    prometheus_url: str,
    query: str,
    time: Optional[str] = None
) -> Dict[str, Any]:
    """
    Execute Prometheus query.

    Args:
        prometheus_url: Prometheus server URL
        query: PromQL query
        time: Optional evaluation timestamp

    Returns:
        Dictionary with query results
    """
    try:
        url = f"{prometheus_url.rstrip('/')}/api/v1/query"

        params = {'query': query}
        if time:
            params['time'] = time

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        if data['status'] == 'success':
            return {
                'success': True,
                'result_type': data['data']['resultType'],
                'result': data['data']['result']
            }
        else:
            return {
                'success': False,
                'error': data.get('error', 'Unknown error')
            }
    except Exception as e:
        logger.error(f"Error querying Prometheus: {str(e)}")
        return {'success': False, 'error': str(e)}


def query_prometheus_range(
    prometheus_url: str,
    query: str,
    start: str,
    end: str,
    step: str = '15s'
) -> Dict[str, Any]:
    """
    Execute Prometheus range query.

    Args:
        prometheus_url: Prometheus server URL
        query: PromQL query
        start: Start timestamp
        end: End timestamp
        step: Query resolution step

    Returns:
        Dictionary with query results
    """
    try:
        url = f"{prometheus_url.rstrip('/')}/api/v1/query_range"

        params = {
            'query': query,
            'start': start,
            'end': end,
            'step': step
        }

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        if data['status'] == 'success':
            return {
                'success': True,
                'result_type': data['data']['resultType'],
                'result': data['data']['result']
            }
        else:
            return {
                'success': False,
                'error': data.get('error', 'Unknown error')
            }
    except Exception as e:
        logger.error(f"Error querying Prometheus range: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_prometheus_targets(prometheus_url: str) -> Dict[str, Any]:
    """
    Get Prometheus scrape targets.

    Args:
        prometheus_url: Prometheus server URL

    Returns:
        Dictionary with targets
    """
    try:
        url = f"{prometheus_url.rstrip('/')}/api/v1/targets"

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        data = response.json()

        if data['status'] == 'success':
            active_targets = []
            for target in data['data']['activeTargets']:
                active_targets.append({
                    'scrape_url': target['scrapeUrl'],
                    'health': target['health'],
                    'labels': target['labels'],
                    'last_scrape': target.get('lastScrape'),
                    'scrape_duration': target.get('lastScrapeDuration')
                })

            return {
                'success': True,
                'active_targets': active_targets,
                'count': len(active_targets)
            }
        else:
            return {
                'success': False,
                'error': data.get('error', 'Unknown error')
            }
    except Exception as e:
        logger.error(f"Error getting Prometheus targets: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_prometheus_alerts(prometheus_url: str) -> Dict[str, Any]:
    """
    Get Prometheus alerts.

    Args:
        prometheus_url: Prometheus server URL

    Returns:
        Dictionary with alerts
    """
    try:
        url = f"{prometheus_url.rstrip('/')}/api/v1/alerts"

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        data = response.json()

        if data['status'] == 'success':
            alerts = []
            for alert in data['data']['alerts']:
                alerts.append({
                    'name': alert['labels'].get('alertname'),
                    'state': alert['state'],
                    'labels': alert['labels'],
                    'annotations': alert.get('annotations', {}),
                    'active_at': alert.get('activeAt'),
                    'value': alert.get('value')
                })

            return {
                'success': True,
                'alerts': alerts,
                'count': len(alerts)
            }
        else:
            return {
                'success': False,
                'error': data.get('error', 'Unknown error')
            }
    except Exception as e:
        logger.error(f"Error getting Prometheus alerts: {str(e)}")
        return {'success': False, 'error': str(e)}


# ============================================================================
# DATADOG TOOLS
# ============================================================================

def _get_datadog_headers(api_key: Optional[str] = None, app_key: Optional[str] = None):
    """Get Datadog API headers."""
    import os

    if not api_key:
        api_key = os.environ.get('DATADOG_API_KEY')
    if not app_key:
        app_key = os.environ.get('DATADOG_APP_KEY')

    if not api_key or not app_key:
        raise Exception("DATADOG_API_KEY and DATADOG_APP_KEY required")

    return {
        'DD-API-KEY': api_key,
        'DD-APPLICATION-KEY': app_key,
        'Content-Type': 'application/json'
    }


def query_datadog_metrics(
    query: str,
    start: int,
    end: int,
    api_key: Optional[str] = None,
    app_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Query Datadog metrics.

    Args:
        query: Metric query
        start: Start timestamp (Unix epoch)
        end: End timestamp (Unix epoch)
        api_key: Datadog API key
        app_key: Datadog application key

    Returns:
        Dictionary with metrics
    """
    try:
        headers = _get_datadog_headers(api_key, app_key)

        url = "https://api.datadoghq.com/api/v1/query"

        params = {
            'query': query,
            'from': start,
            'to': end
        }

        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        return {
            'success': True,
            'status': data.get('status'),
            'series': data.get('series', []),
            'query': query
        }
    except Exception as e:
        logger.error(f"Error querying Datadog metrics: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_datadog_monitors(
    api_key: Optional[str] = None,
    app_key: Optional[str] = None,
    tags: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Get Datadog monitors.

    Args:
        api_key: Datadog API key
        app_key: Datadog application key
        tags: Filter by tags

    Returns:
        Dictionary with monitors
    """
    try:
        headers = _get_datadog_headers(api_key, app_key)

        url = "https://api.datadoghq.com/api/v1/monitor"

        params = {}
        if tags:
            params['tags'] = ','.join(tags)

        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()

        monitors = response.json()

        monitor_list = []
        for monitor in monitors:
            monitor_list.append({
                'id': monitor['id'],
                'name': monitor['name'],
                'type': monitor['type'],
                'query': monitor['query'],
                'message': monitor.get('message'),
                'tags': monitor.get('tags', []),
                'overall_state': monitor.get('overall_state')
            })

        return {
            'success': True,
            'count': len(monitor_list),
            'monitors': monitor_list
        }
    except Exception as e:
        logger.error(f"Error getting Datadog monitors: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_datadog_hosts(
    api_key: Optional[str] = None,
    app_key: Optional[str] = None,
    filter: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get Datadog hosts.

    Args:
        api_key: Datadog API key
        app_key: Datadog application key
        filter: Filter hosts

    Returns:
        Dictionary with hosts
    """
    try:
        headers = _get_datadog_headers(api_key, app_key)

        url = "https://api.datadoghq.com/api/v1/hosts"

        params = {}
        if filter:
            params['filter'] = filter

        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        host_list = []
        for host in data.get('host_list', []):
            host_list.append({
                'name': host.get('name'),
                'aliases': host.get('aliases', []),
                'apps': host.get('apps', []),
                'is_up': host.get('is_up'),
                'last_reported_time': host.get('last_reported_time'),
                'tags_by_source': host.get('tags_by_source', {})
            })

        return {
            'success': True,
            'total': data.get('total_matching', 0),
            'count': len(host_list),
            'hosts': host_list
        }
    except Exception as e:
        logger.error(f"Error getting Datadog hosts: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_datadog_events(
    start: int,
    end: int,
    api_key: Optional[str] = None,
    app_key: Optional[str] = None,
    priority: Optional[str] = None,
    tags: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Get Datadog events.

    Args:
        start: Start timestamp (Unix epoch)
        end: End timestamp (Unix epoch)
        api_key: Datadog API key
        app_key: Datadog application key
        priority: Filter by priority (normal, low)
        tags: Filter by tags

    Returns:
        Dictionary with events
    """
    try:
        headers = _get_datadog_headers(api_key, app_key)

        url = "https://api.datadoghq.com/api/v1/events"

        params = {
            'start': start,
            'end': end
        }

        if priority:
            params['priority'] = priority
        if tags:
            params['tags'] = ','.join(tags)

        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        event_list = []
        for event in data.get('events', []):
            event_list.append({
                'id': event.get('id'),
                'title': event.get('title'),
                'text': event.get('text'),
                'tags': event.get('tags', []),
                'priority': event.get('priority'),
                'date_happened': event.get('date_happened'),
                'alert_type': event.get('alert_type')
            })

        return {
            'success': True,
            'count': len(event_list),
            'events': event_list
        }
    except Exception as e:
        logger.error(f"Error getting Datadog events: {str(e)}")
        return {'success': False, 'error': str(e)}


def create_datadog_event(
    title: str,
    text: str,
    api_key: Optional[str] = None,
    app_key: Optional[str] = None,
    alert_type: str = 'info',
    priority: str = 'normal',
    tags: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Create Datadog event.

    Args:
        title: Event title
        text: Event text
        api_key: Datadog API key
        app_key: Datadog application key
        alert_type: Alert type (info, warning, error, success)
        priority: Priority (normal, low)
        tags: Event tags

    Returns:
        Dictionary with result
    """
    try:
        headers = _get_datadog_headers(api_key, app_key)

        url = "https://api.datadoghq.com/api/v1/events"

        payload = {
            'title': title,
            'text': text,
            'alert_type': alert_type,
            'priority': priority
        }

        if tags:
            payload['tags'] = tags

        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()

        data = response.json()

        return {
            'success': True,
            'event': data.get('event')
        }
    except Exception as e:
        logger.error(f"Error creating Datadog event: {str(e)}")
        return {'success': False, 'error': str(e)}


# ============================================================================
# GRAFANA TOOLS
# ============================================================================

def get_grafana_datasources(grafana_url: str, api_key: str) -> Dict[str, Any]:
    """
    Get Grafana datasources.

    Args:
        grafana_url: Grafana server URL
        api_key: Grafana API key

    Returns:
        Dictionary with datasources
    """
    try:
        url = f"{grafana_url.rstrip('/')}/api/datasources"

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        datasources = response.json()

        return {
            'success': True,
            'count': len(datasources),
            'datasources': datasources
        }
    except Exception as e:
        logger.error(f"Error getting Grafana datasources: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_grafana_dashboards(grafana_url: str, api_key: str) -> Dict[str, Any]:
    """
    Get Grafana dashboards.

    Args:
        grafana_url: Grafana server URL
        api_key: Grafana API key

    Returns:
        Dictionary with dashboards
    """
    try:
        url = f"{grafana_url.rstrip('/')}/api/search"

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        params = {'type': 'dash-db'}

        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()

        dashboards = response.json()

        return {
            'success': True,
            'count': len(dashboards),
            'dashboards': dashboards
        }
    except Exception as e:
        logger.error(f"Error getting Grafana dashboards: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_grafana_alerts(grafana_url: str, api_key: str) -> Dict[str, Any]:
    """
    Get Grafana alerts.

    Args:
        grafana_url: Grafana server URL
        api_key: Grafana API key

    Returns:
        Dictionary with alerts
    """
    try:
        url = f"{grafana_url.rstrip('/')}/api/alerts"

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        alerts = response.json()

        return {
            'success': True,
            'count': len(alerts),
            'alerts': alerts
        }
    except Exception as e:
        logger.error(f"Error getting Grafana alerts: {str(e)}")
        return {'success': False, 'error': str(e)}
