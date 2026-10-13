"""Monitoring tools (Prometheus, Datadog, Grafana) for DevOps Agent."""
import requests
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from ..utils import get_logger, assert_safe_url, safe_request

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
        assert_safe_url(prometheus_url)
        url = f"{prometheus_url.rstrip('/')}/api/v1/query"

        params = {'query': query}
        if time:
            params['time'] = time

        response = safe_request('GET', url, params=params, timeout=30)
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
        assert_safe_url(prometheus_url)
        url = f"{prometheus_url.rstrip('/')}/api/v1/query_range"

        params = {
            'query': query,
            'start': start,
            'end': end,
            'step': step
        }

        response = safe_request('GET', url, params=params, timeout=30)
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
        assert_safe_url(prometheus_url)
        url = f"{prometheus_url.rstrip('/')}/api/v1/targets"

        response = safe_request('GET', url, timeout=30)
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
        assert_safe_url(prometheus_url)
        url = f"{prometheus_url.rstrip('/')}/api/v1/alerts"

        response = safe_request('GET', url, timeout=30)
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
    """Datadog API headers from explicit args or the requesting user's saved Datadog."""
    from .integration_auth import credentials
    creds = credentials('datadog', api_key=api_key, app_key=app_key)

    return {
        'DD-API-KEY': creds['api_key'],
        'DD-APPLICATION-KEY': creds['app_key'],
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

        # ssrf-safe: hardcoded Datadog API host
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

        # ssrf-safe: hardcoded Datadog API host
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

        # ssrf-safe: hardcoded Datadog API host
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

        # ssrf-safe: hardcoded Datadog API host
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

        # ssrf-safe: hardcoded Datadog API host
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
        assert_safe_url(grafana_url)
        url = f"{grafana_url.rstrip('/')}/api/datasources"

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        response = safe_request('GET', url, headers=headers, timeout=30)
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
        assert_safe_url(grafana_url)
        url = f"{grafana_url.rstrip('/')}/api/search"

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        params = {'type': 'dash-db'}

        response = safe_request('GET', url, headers=headers, params=params, timeout=30)
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
        assert_safe_url(grafana_url)
        url = f"{grafana_url.rstrip('/')}/api/alerts"

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        response = safe_request('GET', url, headers=headers, timeout=30)
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


# ==================== TOOL REGISTRATION ====================


def get_tools() -> List[Dict[str, Any]]:
    """
    Get list of monitoring tool definitions for the agent.

    Returns:
        List of tool definitions with name, description, input_schema, and handler
    """
    return [
        # Prometheus Tools
        {
            'name': 'query_prometheus',
            'description': 'Execute a PromQL query against a Prometheus server for instant metrics.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'prometheus_url': {
                        'type': 'string',
                        'description': 'Prometheus server URL (e.g., http://prometheus:9090)'
                    },
                    'query': {
                        'type': 'string',
                        'description': 'PromQL query (e.g., up, node_cpu_seconds_total, rate(http_requests_total[5m]))'
                    },
                    'time': {
                        'type': 'string',
                        'description': 'Evaluation timestamp (RFC3339 or Unix timestamp, optional)'
                    }
                },
                'required': ['prometheus_url', 'query']
            },
            'handler': query_prometheus
        },
        {
            'name': 'query_prometheus_range',
            'description': 'Execute a PromQL range query for time-series data over a period.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'prometheus_url': {
                        'type': 'string',
                        'description': 'Prometheus server URL (e.g., http://prometheus:9090)'
                    },
                    'query': {
                        'type': 'string',
                        'description': 'PromQL query'
                    },
                    'start': {
                        'type': 'string',
                        'description': 'Start timestamp (RFC3339 or Unix timestamp)'
                    },
                    'end': {
                        'type': 'string',
                        'description': 'End timestamp (RFC3339 or Unix timestamp)'
                    },
                    'step': {
                        'type': 'string',
                        'description': 'Query resolution step (e.g., 15s, 1m, 5m)',
                        'default': '15s'
                    }
                },
                'required': ['prometheus_url', 'query', 'start', 'end']
            },
            'handler': query_prometheus_range
        },
        {
            'name': 'get_prometheus_targets',
            'description': 'Get all scrape targets configured in Prometheus with their health status.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'prometheus_url': {
                        'type': 'string',
                        'description': 'Prometheus server URL (e.g., http://prometheus:9090)'
                    }
                },
                'required': ['prometheus_url']
            },
            'handler': get_prometheus_targets
        },
        {
            'name': 'get_prometheus_alerts',
            'description': 'Get all active alerts from Prometheus alerting rules.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'prometheus_url': {
                        'type': 'string',
                        'description': 'Prometheus server URL (e.g., http://prometheus:9090)'
                    }
                },
                'required': ['prometheus_url']
            },
            'handler': get_prometheus_alerts
        },
        # Datadog Tools
        {
            'name': 'query_datadog_metrics',
            'description': 'Query metrics from Datadog for a given time range.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'query': {
                        'type': 'string',
                        'description': 'Datadog metric query (e.g., avg:system.cpu.user{*})'
                    },
                    'start': {
                        'type': 'integer',
                        'description': 'Start timestamp (Unix epoch seconds)'
                    },
                    'end': {
                        'type': 'integer',
                        'description': 'End timestamp (Unix epoch seconds)'
                    },
                    'api_key': {
                        'type': 'string',
                        'description': "Datadog API key (omit to use the user's connected Datadog)"
                    },
                    'app_key': {
                        'type': 'string',
                        'description': "Datadog application key (omit to use the user's connected Datadog)"
                    }
                },
                'required': ['query', 'start', 'end']
            },
            'handler': query_datadog_metrics
        },
        {
            'name': 'get_datadog_monitors',
            'description': 'Get all Datadog monitors with their current status.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'api_key': {
                        'type': 'string',
                        'description': "Datadog API key (omit to use the user's connected Datadog)"
                    },
                    'app_key': {
                        'type': 'string',
                        'description': "Datadog application key (omit to use the user's connected Datadog)"
                    },
                    'tags': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Filter monitors by tags'
                    }
                }
            },
            'handler': get_datadog_monitors
        },
        {
            'name': 'get_datadog_hosts',
            'description': 'Get all hosts reporting to Datadog.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'api_key': {
                        'type': 'string',
                        'description': "Datadog API key (omit to use the user's connected Datadog)"
                    },
                    'app_key': {
                        'type': 'string',
                        'description': "Datadog application key (omit to use the user's connected Datadog)"
                    },
                    'filter': {
                        'type': 'string',
                        'description': 'Filter string for hosts'
                    }
                }
            },
            'handler': get_datadog_hosts
        },
        {
            'name': 'get_datadog_events',
            'description': 'Get events from Datadog for a given time range.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'start': {
                        'type': 'integer',
                        'description': 'Start timestamp (Unix epoch seconds)'
                    },
                    'end': {
                        'type': 'integer',
                        'description': 'End timestamp (Unix epoch seconds)'
                    },
                    'api_key': {
                        'type': 'string',
                        'description': "Datadog API key (omit to use the user's connected Datadog)"
                    },
                    'app_key': {
                        'type': 'string',
                        'description': "Datadog application key (omit to use the user's connected Datadog)"
                    },
                    'priority': {
                        'type': 'string',
                        'description': 'Filter by priority (normal, low)',
                        'enum': ['normal', 'low']
                    },
                    'tags': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Filter events by tags'
                    }
                },
                'required': ['start', 'end']
            },
            'handler': get_datadog_events
        },
        {
            'name': 'create_datadog_event',
            'description': 'Create a new event in Datadog.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'title': {
                        'type': 'string',
                        'description': 'Event title'
                    },
                    'text': {
                        'type': 'string',
                        'description': 'Event body text (supports Markdown)'
                    },
                    'api_key': {
                        'type': 'string',
                        'description': "Datadog API key (omit to use the user's connected Datadog)"
                    },
                    'app_key': {
                        'type': 'string',
                        'description': "Datadog application key (omit to use the user's connected Datadog)"
                    },
                    'alert_type': {
                        'type': 'string',
                        'description': 'Alert type',
                        'enum': ['info', 'warning', 'error', 'success'],
                        'default': 'info'
                    },
                    'priority': {
                        'type': 'string',
                        'description': 'Event priority',
                        'enum': ['normal', 'low'],
                        'default': 'normal'
                    },
                    'tags': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Event tags'
                    }
                },
                'required': ['title', 'text']
            },
            'handler': create_datadog_event
        },
        # Grafana Tools
        {
            'name': 'get_grafana_datasources',
            'description': 'Get all configured datasources in Grafana.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'grafana_url': {
                        'type': 'string',
                        'description': 'Grafana server URL (e.g., http://grafana:3000)'
                    },
                    'api_key': {
                        'type': 'string',
                        'description': 'Grafana API key or service account token'
                    }
                },
                'required': ['grafana_url', 'api_key']
            },
            'handler': get_grafana_datasources
        },
        {
            'name': 'get_grafana_dashboards',
            'description': 'Get all dashboards in Grafana.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'grafana_url': {
                        'type': 'string',
                        'description': 'Grafana server URL (e.g., http://grafana:3000)'
                    },
                    'api_key': {
                        'type': 'string',
                        'description': 'Grafana API key or service account token'
                    }
                },
                'required': ['grafana_url', 'api_key']
            },
            'handler': get_grafana_dashboards
        },
        {
            'name': 'get_grafana_alerts',
            'description': 'Get all alerts configured in Grafana.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'grafana_url': {
                        'type': 'string',
                        'description': 'Grafana server URL (e.g., http://grafana:3000)'
                    },
                    'api_key': {
                        'type': 'string',
                        'description': 'Grafana API key or service account token'
                    }
                },
                'required': ['grafana_url', 'api_key']
            },
            'handler': get_grafana_alerts
        }
    ]
