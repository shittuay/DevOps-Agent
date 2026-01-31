"""PagerDuty and OpsGenie alerting tools for DevOps Agent."""
import os
import requests
from typing import Dict, Any, Optional, List
from datetime import datetime
from ..utils import get_logger

logger = get_logger(__name__)


# ============================================================================
# PAGERDUTY TOOLS
# ============================================================================

def _get_pagerduty_headers(api_key: Optional[str] = None) -> Dict[str, str]:
    """Get PagerDuty API headers."""
    if not api_key:
        api_key = os.environ.get('PAGERDUTY_API_KEY')

    if not api_key:
        raise Exception("PAGERDUTY_API_KEY not found. Set it in environment or pass as parameter.")

    return {
        'Authorization': f'Token token={api_key}',
        'Content-Type': 'application/json',
        'Accept': 'application/vnd.pagerduty+json;version=2'
    }


def pagerduty_create_incident(
    title: str,
    service_id: str,
    urgency: str = 'high',
    body: Optional[str] = None,
    escalation_policy_id: Optional[str] = None,
    incident_key: Optional[str] = None,
    api_key: Optional[str] = None,
    from_email: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a PagerDuty incident.

    Args:
        title: Incident title
        service_id: PagerDuty service ID
        urgency: Urgency level (high, low)
        body: Incident body/description
        escalation_policy_id: Escalation policy ID (optional)
        incident_key: Deduplication key (optional)
        api_key: PagerDuty API key
        from_email: Email of user creating incident

    Returns:
        Dictionary with incident details
    """
    try:
        headers = _get_pagerduty_headers(api_key)

        if not from_email:
            from_email = os.environ.get('PAGERDUTY_FROM_EMAIL', 'devops-agent@example.com')

        headers['From'] = from_email

        incident_data = {
            'incident': {
                'type': 'incident',
                'title': title,
                'service': {
                    'id': service_id,
                    'type': 'service_reference'
                },
                'urgency': urgency
            }
        }

        if body:
            incident_data['incident']['body'] = {
                'type': 'incident_body',
                'details': body
            }

        if escalation_policy_id:
            incident_data['incident']['escalation_policy'] = {
                'id': escalation_policy_id,
                'type': 'escalation_policy_reference'
            }

        if incident_key:
            incident_data['incident']['incident_key'] = incident_key

        response = requests.post(
            'https://api.pagerduty.com/incidents',
            headers=headers,
            json=incident_data,
            timeout=30
        )
        response.raise_for_status()

        incident = response.json().get('incident', {})

        return {
            'success': True,
            'incident_id': incident.get('id'),
            'incident_number': incident.get('incident_number'),
            'title': incident.get('title'),
            'status': incident.get('status'),
            'urgency': incident.get('urgency'),
            'html_url': incident.get('html_url'),
            'message': f'Incident created: {incident.get("title")}'
        }
    except requests.exceptions.HTTPError as e:
        logger.error(f"PagerDuty API error: {str(e)}")
        return {'success': False, 'error': f'API error: {str(e)}'}
    except Exception as e:
        logger.error(f"Error creating PagerDuty incident: {str(e)}")
        return {'success': False, 'error': str(e)}


def pagerduty_list_incidents(
    status: Optional[List[str]] = None,
    urgency: Optional[List[str]] = None,
    service_ids: Optional[List[str]] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 25,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    List PagerDuty incidents.

    Args:
        status: Filter by status (triggered, acknowledged, resolved)
        urgency: Filter by urgency (high, low)
        service_ids: Filter by service IDs
        since: Start date (ISO 8601)
        until: End date (ISO 8601)
        limit: Maximum number of incidents to return
        api_key: PagerDuty API key

    Returns:
        Dictionary with incidents list
    """
    try:
        headers = _get_pagerduty_headers(api_key)

        params = {'limit': limit}

        if status:
            params['statuses[]'] = status
        if urgency:
            params['urgencies[]'] = urgency
        if service_ids:
            params['service_ids[]'] = service_ids
        if since:
            params['since'] = since
        if until:
            params['until'] = until

        response = requests.get(
            'https://api.pagerduty.com/incidents',
            headers=headers,
            params=params,
            timeout=30
        )
        response.raise_for_status()

        data = response.json()
        incidents = []

        for incident in data.get('incidents', []):
            incidents.append({
                'id': incident.get('id'),
                'incident_number': incident.get('incident_number'),
                'title': incident.get('title'),
                'status': incident.get('status'),
                'urgency': incident.get('urgency'),
                'created_at': incident.get('created_at'),
                'service': incident.get('service', {}).get('summary'),
                'html_url': incident.get('html_url')
            })

        return {
            'success': True,
            'count': len(incidents),
            'incidents': incidents
        }
    except Exception as e:
        logger.error(f"Error listing PagerDuty incidents: {str(e)}")
        return {'success': False, 'error': str(e)}


def pagerduty_get_incident(
    incident_id: str,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get details of a PagerDuty incident.

    Args:
        incident_id: PagerDuty incident ID
        api_key: PagerDuty API key

    Returns:
        Dictionary with incident details
    """
    try:
        headers = _get_pagerduty_headers(api_key)

        response = requests.get(
            f'https://api.pagerduty.com/incidents/{incident_id}',
            headers=headers,
            timeout=30
        )
        response.raise_for_status()

        incident = response.json().get('incident', {})

        return {
            'success': True,
            'incident': {
                'id': incident.get('id'),
                'incident_number': incident.get('incident_number'),
                'title': incident.get('title'),
                'description': incident.get('description'),
                'status': incident.get('status'),
                'urgency': incident.get('urgency'),
                'created_at': incident.get('created_at'),
                'last_status_change_at': incident.get('last_status_change_at'),
                'service': incident.get('service', {}).get('summary'),
                'escalation_policy': incident.get('escalation_policy', {}).get('summary'),
                'teams': [t.get('summary') for t in incident.get('teams', [])],
                'assignments': [a.get('assignee', {}).get('summary') for a in incident.get('assignments', [])],
                'html_url': incident.get('html_url')
            }
        }
    except Exception as e:
        logger.error(f"Error getting PagerDuty incident: {str(e)}")
        return {'success': False, 'error': str(e)}


def pagerduty_update_incident(
    incident_id: str,
    status: Optional[str] = None,
    resolution: Optional[str] = None,
    escalation_level: Optional[int] = None,
    api_key: Optional[str] = None,
    from_email: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update a PagerDuty incident (acknowledge, resolve, escalate).

    Args:
        incident_id: PagerDuty incident ID
        status: New status (acknowledged, resolved)
        resolution: Resolution note (when resolving)
        escalation_level: Escalation level to escalate to
        api_key: PagerDuty API key
        from_email: Email of user updating incident

    Returns:
        Dictionary with update result
    """
    try:
        headers = _get_pagerduty_headers(api_key)

        if not from_email:
            from_email = os.environ.get('PAGERDUTY_FROM_EMAIL', 'devops-agent@example.com')

        headers['From'] = from_email

        incident_data = {
            'incident': {
                'id': incident_id,
                'type': 'incident_reference'
            }
        }

        if status:
            incident_data['incident']['status'] = status

        if resolution:
            incident_data['incident']['resolution'] = resolution

        if escalation_level is not None:
            incident_data['incident']['escalation_level'] = escalation_level

        response = requests.put(
            f'https://api.pagerduty.com/incidents/{incident_id}',
            headers=headers,
            json=incident_data,
            timeout=30
        )
        response.raise_for_status()

        incident = response.json().get('incident', {})

        return {
            'success': True,
            'incident_id': incident.get('id'),
            'status': incident.get('status'),
            'message': f'Incident {incident_id} updated to status: {incident.get("status")}'
        }
    except Exception as e:
        logger.error(f"Error updating PagerDuty incident: {str(e)}")
        return {'success': False, 'error': str(e)}


def pagerduty_add_note(
    incident_id: str,
    content: str,
    api_key: Optional[str] = None,
    from_email: Optional[str] = None
) -> Dict[str, Any]:
    """
    Add a note to a PagerDuty incident.

    Args:
        incident_id: PagerDuty incident ID
        content: Note content
        api_key: PagerDuty API key
        from_email: Email of user adding note

    Returns:
        Dictionary with note result
    """
    try:
        headers = _get_pagerduty_headers(api_key)

        if not from_email:
            from_email = os.environ.get('PAGERDUTY_FROM_EMAIL', 'devops-agent@example.com')

        headers['From'] = from_email

        note_data = {
            'note': {
                'content': content
            }
        }

        response = requests.post(
            f'https://api.pagerduty.com/incidents/{incident_id}/notes',
            headers=headers,
            json=note_data,
            timeout=30
        )
        response.raise_for_status()

        note = response.json().get('note', {})

        return {
            'success': True,
            'note_id': note.get('id'),
            'content': note.get('content'),
            'created_at': note.get('created_at'),
            'message': 'Note added to incident'
        }
    except Exception as e:
        logger.error(f"Error adding note to PagerDuty incident: {str(e)}")
        return {'success': False, 'error': str(e)}


def pagerduty_list_services(
    api_key: Optional[str] = None,
    limit: int = 25
) -> Dict[str, Any]:
    """
    List PagerDuty services.

    Args:
        api_key: PagerDuty API key
        limit: Maximum number of services to return

    Returns:
        Dictionary with services list
    """
    try:
        headers = _get_pagerduty_headers(api_key)

        response = requests.get(
            'https://api.pagerduty.com/services',
            headers=headers,
            params={'limit': limit},
            timeout=30
        )
        response.raise_for_status()

        services = []
        for service in response.json().get('services', []):
            services.append({
                'id': service.get('id'),
                'name': service.get('name'),
                'description': service.get('description'),
                'status': service.get('status'),
                'escalation_policy': service.get('escalation_policy', {}).get('summary'),
                'html_url': service.get('html_url')
            })

        return {
            'success': True,
            'count': len(services),
            'services': services
        }
    except Exception as e:
        logger.error(f"Error listing PagerDuty services: {str(e)}")
        return {'success': False, 'error': str(e)}


def pagerduty_list_oncalls(
    schedule_ids: Optional[List[str]] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    List current on-call users in PagerDuty.

    Args:
        schedule_ids: Filter by schedule IDs
        api_key: PagerDuty API key

    Returns:
        Dictionary with on-call information
    """
    try:
        headers = _get_pagerduty_headers(api_key)

        params = {}
        if schedule_ids:
            params['schedule_ids[]'] = schedule_ids

        response = requests.get(
            'https://api.pagerduty.com/oncalls',
            headers=headers,
            params=params,
            timeout=30
        )
        response.raise_for_status()

        oncalls = []
        for oncall in response.json().get('oncalls', []):
            oncalls.append({
                'user': oncall.get('user', {}).get('summary'),
                'user_email': oncall.get('user', {}).get('email'),
                'schedule': oncall.get('schedule', {}).get('summary'),
                'escalation_policy': oncall.get('escalation_policy', {}).get('summary'),
                'escalation_level': oncall.get('escalation_level'),
                'start': oncall.get('start'),
                'end': oncall.get('end')
            })

        return {
            'success': True,
            'count': len(oncalls),
            'oncalls': oncalls
        }
    except Exception as e:
        logger.error(f"Error listing PagerDuty on-calls: {str(e)}")
        return {'success': False, 'error': str(e)}


# ============================================================================
# OPSGENIE TOOLS
# ============================================================================

def _get_opsgenie_headers(api_key: Optional[str] = None) -> Dict[str, str]:
    """Get OpsGenie API headers."""
    if not api_key:
        api_key = os.environ.get('OPSGENIE_API_KEY')

    if not api_key:
        raise Exception("OPSGENIE_API_KEY not found. Set it in environment or pass as parameter.")

    return {
        'Authorization': f'GenieKey {api_key}',
        'Content-Type': 'application/json'
    }


def _get_opsgenie_base_url() -> str:
    """Get OpsGenie base URL (supports EU region)."""
    region = os.environ.get('OPSGENIE_REGION', 'us').lower()
    if region == 'eu':
        return 'https://api.eu.opsgenie.com/v2'
    return 'https://api.opsgenie.com/v2'


def opsgenie_create_alert(
    message: str,
    priority: str = 'P3',
    description: Optional[str] = None,
    alias: Optional[str] = None,
    source: Optional[str] = None,
    tags: Optional[List[str]] = None,
    entity: Optional[str] = None,
    responders: Optional[List[Dict[str, str]]] = None,
    details: Optional[Dict[str, str]] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create an OpsGenie alert.

    Args:
        message: Alert message (required)
        priority: Priority (P1-P5, P1 is highest)
        description: Alert description
        alias: Deduplication alias
        source: Alert source
        tags: Alert tags
        entity: Related entity
        responders: List of responders (e.g., [{"type": "team", "name": "ops"}])
        details: Additional details as key-value pairs
        api_key: OpsGenie API key

    Returns:
        Dictionary with alert details
    """
    try:
        headers = _get_opsgenie_headers(api_key)
        base_url = _get_opsgenie_base_url()

        alert_data = {
            'message': message,
            'priority': priority
        }

        if description:
            alert_data['description'] = description
        if alias:
            alert_data['alias'] = alias
        if source:
            alert_data['source'] = source
        if tags:
            alert_data['tags'] = tags
        if entity:
            alert_data['entity'] = entity
        if responders:
            alert_data['responders'] = responders
        if details:
            alert_data['details'] = details

        response = requests.post(
            f'{base_url}/alerts',
            headers=headers,
            json=alert_data,
            timeout=30
        )
        response.raise_for_status()

        result = response.json()

        return {
            'success': True,
            'request_id': result.get('requestId'),
            'alert_id': result.get('alertId'),
            'message': message,
            'priority': priority,
            'result': result.get('result')
        }
    except requests.exceptions.HTTPError as e:
        logger.error(f"OpsGenie API error: {str(e)}")
        return {'success': False, 'error': f'API error: {str(e)}'}
    except Exception as e:
        logger.error(f"Error creating OpsGenie alert: {str(e)}")
        return {'success': False, 'error': str(e)}


def opsgenie_list_alerts(
    query: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
    sort: str = 'createdAt',
    order: str = 'desc',
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    List OpsGenie alerts.

    Args:
        query: Search query
        status: Filter by status (open, closed)
        limit: Maximum number of alerts
        sort: Sort field (createdAt, updatedAt, etc.)
        order: Sort order (asc, desc)
        api_key: OpsGenie API key

    Returns:
        Dictionary with alerts list
    """
    try:
        headers = _get_opsgenie_headers(api_key)
        base_url = _get_opsgenie_base_url()

        params = {
            'limit': limit,
            'sort': sort,
            'order': order
        }

        if query:
            params['query'] = query
        elif status:
            params['query'] = f'status={status}'

        response = requests.get(
            f'{base_url}/alerts',
            headers=headers,
            params=params,
            timeout=30
        )
        response.raise_for_status()

        data = response.json()
        alerts = []

        for alert in data.get('data', []):
            alerts.append({
                'id': alert.get('id'),
                'tiny_id': alert.get('tinyId'),
                'message': alert.get('message'),
                'status': alert.get('status'),
                'acknowledged': alert.get('acknowledged'),
                'priority': alert.get('priority'),
                'created_at': alert.get('createdAt'),
                'updated_at': alert.get('updatedAt'),
                'source': alert.get('source'),
                'tags': alert.get('tags', [])
            })

        return {
            'success': True,
            'count': len(alerts),
            'alerts': alerts
        }
    except Exception as e:
        logger.error(f"Error listing OpsGenie alerts: {str(e)}")
        return {'success': False, 'error': str(e)}


def opsgenie_get_alert(
    alert_id: str,
    identifier_type: str = 'id',
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get details of an OpsGenie alert.

    Args:
        alert_id: Alert identifier
        identifier_type: Type of identifier (id, alias, tiny)
        api_key: OpsGenie API key

    Returns:
        Dictionary with alert details
    """
    try:
        headers = _get_opsgenie_headers(api_key)
        base_url = _get_opsgenie_base_url()

        response = requests.get(
            f'{base_url}/alerts/{alert_id}',
            headers=headers,
            params={'identifierType': identifier_type},
            timeout=30
        )
        response.raise_for_status()

        alert = response.json().get('data', {})

        return {
            'success': True,
            'alert': {
                'id': alert.get('id'),
                'tiny_id': alert.get('tinyId'),
                'alias': alert.get('alias'),
                'message': alert.get('message'),
                'description': alert.get('description'),
                'status': alert.get('status'),
                'acknowledged': alert.get('acknowledged'),
                'is_seen': alert.get('isSeen'),
                'priority': alert.get('priority'),
                'created_at': alert.get('createdAt'),
                'updated_at': alert.get('updatedAt'),
                'source': alert.get('source'),
                'owner': alert.get('owner'),
                'responders': alert.get('responders', []),
                'tags': alert.get('tags', []),
                'details': alert.get('details', {}),
                'actions': alert.get('actions', [])
            }
        }
    except Exception as e:
        logger.error(f"Error getting OpsGenie alert: {str(e)}")
        return {'success': False, 'error': str(e)}


def opsgenie_acknowledge_alert(
    alert_id: str,
    identifier_type: str = 'id',
    user: Optional[str] = None,
    note: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Acknowledge an OpsGenie alert.

    Args:
        alert_id: Alert identifier
        identifier_type: Type of identifier (id, alias, tiny)
        user: User acknowledging the alert
        note: Acknowledgment note
        api_key: OpsGenie API key

    Returns:
        Dictionary with result
    """
    try:
        headers = _get_opsgenie_headers(api_key)
        base_url = _get_opsgenie_base_url()

        ack_data = {}
        if user:
            ack_data['user'] = user
        if note:
            ack_data['note'] = note

        response = requests.post(
            f'{base_url}/alerts/{alert_id}/acknowledge',
            headers=headers,
            params={'identifierType': identifier_type},
            json=ack_data,
            timeout=30
        )
        response.raise_for_status()

        result = response.json()

        return {
            'success': True,
            'request_id': result.get('requestId'),
            'result': result.get('result'),
            'message': f'Alert {alert_id} acknowledged'
        }
    except Exception as e:
        logger.error(f"Error acknowledging OpsGenie alert: {str(e)}")
        return {'success': False, 'error': str(e)}


def opsgenie_close_alert(
    alert_id: str,
    identifier_type: str = 'id',
    user: Optional[str] = None,
    note: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Close an OpsGenie alert.

    Args:
        alert_id: Alert identifier
        identifier_type: Type of identifier (id, alias, tiny)
        user: User closing the alert
        note: Closing note
        api_key: OpsGenie API key

    Returns:
        Dictionary with result
    """
    try:
        headers = _get_opsgenie_headers(api_key)
        base_url = _get_opsgenie_base_url()

        close_data = {}
        if user:
            close_data['user'] = user
        if note:
            close_data['note'] = note

        response = requests.post(
            f'{base_url}/alerts/{alert_id}/close',
            headers=headers,
            params={'identifierType': identifier_type},
            json=close_data,
            timeout=30
        )
        response.raise_for_status()

        result = response.json()

        return {
            'success': True,
            'request_id': result.get('requestId'),
            'result': result.get('result'),
            'message': f'Alert {alert_id} closed'
        }
    except Exception as e:
        logger.error(f"Error closing OpsGenie alert: {str(e)}")
        return {'success': False, 'error': str(e)}


def opsgenie_add_note(
    alert_id: str,
    note: str,
    identifier_type: str = 'id',
    user: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Add a note to an OpsGenie alert.

    Args:
        alert_id: Alert identifier
        note: Note content
        identifier_type: Type of identifier (id, alias, tiny)
        user: User adding the note
        api_key: OpsGenie API key

    Returns:
        Dictionary with result
    """
    try:
        headers = _get_opsgenie_headers(api_key)
        base_url = _get_opsgenie_base_url()

        note_data = {'note': note}
        if user:
            note_data['user'] = user

        response = requests.post(
            f'{base_url}/alerts/{alert_id}/notes',
            headers=headers,
            params={'identifierType': identifier_type},
            json=note_data,
            timeout=30
        )
        response.raise_for_status()

        result = response.json()

        return {
            'success': True,
            'request_id': result.get('requestId'),
            'result': result.get('result'),
            'message': 'Note added to alert'
        }
    except Exception as e:
        logger.error(f"Error adding note to OpsGenie alert: {str(e)}")
        return {'success': False, 'error': str(e)}


def opsgenie_list_schedules(
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    List OpsGenie schedules.

    Args:
        api_key: OpsGenie API key

    Returns:
        Dictionary with schedules list
    """
    try:
        headers = _get_opsgenie_headers(api_key)
        base_url = _get_opsgenie_base_url()

        response = requests.get(
            f'{base_url}/schedules',
            headers=headers,
            timeout=30
        )
        response.raise_for_status()

        schedules = []
        for schedule in response.json().get('data', []):
            schedules.append({
                'id': schedule.get('id'),
                'name': schedule.get('name'),
                'description': schedule.get('description'),
                'timezone': schedule.get('timezone'),
                'enabled': schedule.get('enabled'),
                'owner_team': schedule.get('ownerTeam', {}).get('name')
            })

        return {
            'success': True,
            'count': len(schedules),
            'schedules': schedules
        }
    except Exception as e:
        logger.error(f"Error listing OpsGenie schedules: {str(e)}")
        return {'success': False, 'error': str(e)}


def opsgenie_get_oncall(
    schedule_id: str,
    flat: bool = True,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get current on-call users for an OpsGenie schedule.

    Args:
        schedule_id: Schedule identifier (ID or name)
        flat: Return flat list of participants
        api_key: OpsGenie API key

    Returns:
        Dictionary with on-call information
    """
    try:
        headers = _get_opsgenie_headers(api_key)
        base_url = _get_opsgenie_base_url()

        response = requests.get(
            f'{base_url}/schedules/{schedule_id}/on-calls',
            headers=headers,
            params={'flat': str(flat).lower()},
            timeout=30
        )
        response.raise_for_status()

        data = response.json().get('data', {})

        oncall_participants = []
        for participant in data.get('onCallParticipants', []):
            oncall_participants.append({
                'name': participant.get('name'),
                'type': participant.get('type'),
                'id': participant.get('id')
            })

        return {
            'success': True,
            'schedule': schedule_id,
            'oncall_participants': oncall_participants
        }
    except Exception as e:
        logger.error(f"Error getting OpsGenie on-call: {str(e)}")
        return {'success': False, 'error': str(e)}


def opsgenie_escalate_alert(
    alert_id: str,
    escalation_id: str,
    identifier_type: str = 'id',
    user: Optional[str] = None,
    note: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Escalate an OpsGenie alert to next level.

    Args:
        alert_id: Alert identifier
        escalation_id: Escalation policy ID or name
        identifier_type: Type of identifier (id, alias, tiny)
        user: User escalating the alert
        note: Escalation note
        api_key: OpsGenie API key

    Returns:
        Dictionary with result
    """
    try:
        headers = _get_opsgenie_headers(api_key)
        base_url = _get_opsgenie_base_url()

        escalate_data = {
            'escalation': {'id': escalation_id}
        }
        if user:
            escalate_data['user'] = user
        if note:
            escalate_data['note'] = note

        response = requests.post(
            f'{base_url}/alerts/{alert_id}/escalate',
            headers=headers,
            params={'identifierType': identifier_type},
            json=escalate_data,
            timeout=30
        )
        response.raise_for_status()

        result = response.json()

        return {
            'success': True,
            'request_id': result.get('requestId'),
            'result': result.get('result'),
            'message': f'Alert {alert_id} escalated'
        }
    except Exception as e:
        logger.error(f"Error escalating OpsGenie alert: {str(e)}")
        return {'success': False, 'error': str(e)}


# ==================== TOOL REGISTRATION ====================


def get_tools() -> List[Dict[str, Any]]:
    """
    Get list of alerting tool definitions for the agent.

    Returns:
        List of tool definitions with name, description, input_schema, and handler
    """
    return [
        # PagerDuty Tools
        {
            'name': 'pagerduty_create_incident',
            'description': 'Create a new PagerDuty incident to alert on-call responders.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'title': {
                        'type': 'string',
                        'description': 'Incident title'
                    },
                    'service_id': {
                        'type': 'string',
                        'description': 'PagerDuty service ID to create incident for'
                    },
                    'urgency': {
                        'type': 'string',
                        'description': 'Urgency level',
                        'enum': ['high', 'low'],
                        'default': 'high'
                    },
                    'body': {
                        'type': 'string',
                        'description': 'Incident description/body'
                    },
                    'escalation_policy_id': {
                        'type': 'string',
                        'description': 'Escalation policy ID (optional)'
                    },
                    'incident_key': {
                        'type': 'string',
                        'description': 'Deduplication key for the incident'
                    },
                    'api_key': {
                        'type': 'string',
                        'description': 'PagerDuty API key (uses env var if not provided)'
                    },
                    'from_email': {
                        'type': 'string',
                        'description': 'Email of user creating incident'
                    }
                },
                'required': ['title', 'service_id']
            },
            'handler': pagerduty_create_incident
        },
        {
            'name': 'pagerduty_list_incidents',
            'description': 'List PagerDuty incidents with optional filters.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'status': {
                        'type': 'array',
                        'items': {'type': 'string', 'enum': ['triggered', 'acknowledged', 'resolved']},
                        'description': 'Filter by status'
                    },
                    'urgency': {
                        'type': 'array',
                        'items': {'type': 'string', 'enum': ['high', 'low']},
                        'description': 'Filter by urgency'
                    },
                    'service_ids': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Filter by service IDs'
                    },
                    'since': {
                        'type': 'string',
                        'description': 'Start date (ISO 8601 format)'
                    },
                    'until': {
                        'type': 'string',
                        'description': 'End date (ISO 8601 format)'
                    },
                    'limit': {
                        'type': 'integer',
                        'description': 'Maximum incidents to return',
                        'default': 25
                    },
                    'api_key': {
                        'type': 'string',
                        'description': 'PagerDuty API key'
                    }
                }
            },
            'handler': pagerduty_list_incidents
        },
        {
            'name': 'pagerduty_get_incident',
            'description': 'Get details of a specific PagerDuty incident.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'incident_id': {
                        'type': 'string',
                        'description': 'PagerDuty incident ID'
                    },
                    'api_key': {
                        'type': 'string',
                        'description': 'PagerDuty API key'
                    }
                },
                'required': ['incident_id']
            },
            'handler': pagerduty_get_incident
        },
        {
            'name': 'pagerduty_update_incident',
            'description': 'Update a PagerDuty incident (acknowledge, resolve, escalate).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'incident_id': {
                        'type': 'string',
                        'description': 'PagerDuty incident ID'
                    },
                    'status': {
                        'type': 'string',
                        'description': 'New status',
                        'enum': ['acknowledged', 'resolved']
                    },
                    'resolution': {
                        'type': 'string',
                        'description': 'Resolution note (when resolving)'
                    },
                    'escalation_level': {
                        'type': 'integer',
                        'description': 'Escalation level to escalate to'
                    },
                    'api_key': {
                        'type': 'string',
                        'description': 'PagerDuty API key'
                    },
                    'from_email': {
                        'type': 'string',
                        'description': 'Email of user updating incident'
                    }
                },
                'required': ['incident_id']
            },
            'handler': pagerduty_update_incident
        },
        {
            'name': 'pagerduty_add_note',
            'description': 'Add a note to a PagerDuty incident.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'incident_id': {
                        'type': 'string',
                        'description': 'PagerDuty incident ID'
                    },
                    'content': {
                        'type': 'string',
                        'description': 'Note content'
                    },
                    'api_key': {
                        'type': 'string',
                        'description': 'PagerDuty API key'
                    },
                    'from_email': {
                        'type': 'string',
                        'description': 'Email of user adding note'
                    }
                },
                'required': ['incident_id', 'content']
            },
            'handler': pagerduty_add_note
        },
        {
            'name': 'pagerduty_list_services',
            'description': 'List PagerDuty services.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'api_key': {
                        'type': 'string',
                        'description': 'PagerDuty API key'
                    },
                    'limit': {
                        'type': 'integer',
                        'description': 'Maximum services to return',
                        'default': 25
                    }
                }
            },
            'handler': pagerduty_list_services
        },
        {
            'name': 'pagerduty_list_oncalls',
            'description': 'List current on-call users in PagerDuty.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'schedule_ids': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Filter by schedule IDs'
                    },
                    'api_key': {
                        'type': 'string',
                        'description': 'PagerDuty API key'
                    }
                }
            },
            'handler': pagerduty_list_oncalls
        },
        # OpsGenie Tools
        {
            'name': 'opsgenie_create_alert',
            'description': 'Create an OpsGenie alert to notify responders.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'message': {
                        'type': 'string',
                        'description': 'Alert message (required)'
                    },
                    'priority': {
                        'type': 'string',
                        'description': 'Priority (P1=Critical, P2=High, P3=Moderate, P4=Low, P5=Informational)',
                        'enum': ['P1', 'P2', 'P3', 'P4', 'P5'],
                        'default': 'P3'
                    },
                    'description': {
                        'type': 'string',
                        'description': 'Alert description'
                    },
                    'alias': {
                        'type': 'string',
                        'description': 'Deduplication alias'
                    },
                    'source': {
                        'type': 'string',
                        'description': 'Alert source'
                    },
                    'tags': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Alert tags'
                    },
                    'entity': {
                        'type': 'string',
                        'description': 'Related entity (e.g., server name)'
                    },
                    'responders': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'type': {'type': 'string', 'enum': ['team', 'user', 'escalation', 'schedule']},
                                'name': {'type': 'string'},
                                'id': {'type': 'string'}
                            }
                        },
                        'description': 'Responders to notify'
                    },
                    'details': {
                        'type': 'object',
                        'description': 'Additional details as key-value pairs'
                    },
                    'api_key': {
                        'type': 'string',
                        'description': 'OpsGenie API key'
                    }
                },
                'required': ['message']
            },
            'handler': opsgenie_create_alert
        },
        {
            'name': 'opsgenie_list_alerts',
            'description': 'List OpsGenie alerts with optional filters.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'query': {
                        'type': 'string',
                        'description': 'Search query (OpsGenie query syntax)'
                    },
                    'status': {
                        'type': 'string',
                        'description': 'Filter by status',
                        'enum': ['open', 'closed']
                    },
                    'limit': {
                        'type': 'integer',
                        'description': 'Maximum alerts to return',
                        'default': 20
                    },
                    'sort': {
                        'type': 'string',
                        'description': 'Sort field',
                        'default': 'createdAt'
                    },
                    'order': {
                        'type': 'string',
                        'description': 'Sort order',
                        'enum': ['asc', 'desc'],
                        'default': 'desc'
                    },
                    'api_key': {
                        'type': 'string',
                        'description': 'OpsGenie API key'
                    }
                }
            },
            'handler': opsgenie_list_alerts
        },
        {
            'name': 'opsgenie_get_alert',
            'description': 'Get details of a specific OpsGenie alert.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'alert_id': {
                        'type': 'string',
                        'description': 'Alert identifier'
                    },
                    'identifier_type': {
                        'type': 'string',
                        'description': 'Type of identifier',
                        'enum': ['id', 'alias', 'tiny'],
                        'default': 'id'
                    },
                    'api_key': {
                        'type': 'string',
                        'description': 'OpsGenie API key'
                    }
                },
                'required': ['alert_id']
            },
            'handler': opsgenie_get_alert
        },
        {
            'name': 'opsgenie_acknowledge_alert',
            'description': 'Acknowledge an OpsGenie alert.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'alert_id': {
                        'type': 'string',
                        'description': 'Alert identifier'
                    },
                    'identifier_type': {
                        'type': 'string',
                        'description': 'Type of identifier',
                        'enum': ['id', 'alias', 'tiny'],
                        'default': 'id'
                    },
                    'user': {
                        'type': 'string',
                        'description': 'User acknowledging the alert'
                    },
                    'note': {
                        'type': 'string',
                        'description': 'Acknowledgment note'
                    },
                    'api_key': {
                        'type': 'string',
                        'description': 'OpsGenie API key'
                    }
                },
                'required': ['alert_id']
            },
            'handler': opsgenie_acknowledge_alert
        },
        {
            'name': 'opsgenie_close_alert',
            'description': 'Close an OpsGenie alert.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'alert_id': {
                        'type': 'string',
                        'description': 'Alert identifier'
                    },
                    'identifier_type': {
                        'type': 'string',
                        'description': 'Type of identifier',
                        'enum': ['id', 'alias', 'tiny'],
                        'default': 'id'
                    },
                    'user': {
                        'type': 'string',
                        'description': 'User closing the alert'
                    },
                    'note': {
                        'type': 'string',
                        'description': 'Closing note'
                    },
                    'api_key': {
                        'type': 'string',
                        'description': 'OpsGenie API key'
                    }
                },
                'required': ['alert_id']
            },
            'handler': opsgenie_close_alert
        },
        {
            'name': 'opsgenie_add_note',
            'description': 'Add a note to an OpsGenie alert.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'alert_id': {
                        'type': 'string',
                        'description': 'Alert identifier'
                    },
                    'note': {
                        'type': 'string',
                        'description': 'Note content'
                    },
                    'identifier_type': {
                        'type': 'string',
                        'description': 'Type of identifier',
                        'enum': ['id', 'alias', 'tiny'],
                        'default': 'id'
                    },
                    'user': {
                        'type': 'string',
                        'description': 'User adding the note'
                    },
                    'api_key': {
                        'type': 'string',
                        'description': 'OpsGenie API key'
                    }
                },
                'required': ['alert_id', 'note']
            },
            'handler': opsgenie_add_note
        },
        {
            'name': 'opsgenie_list_schedules',
            'description': 'List OpsGenie on-call schedules.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'api_key': {
                        'type': 'string',
                        'description': 'OpsGenie API key'
                    }
                }
            },
            'handler': opsgenie_list_schedules
        },
        {
            'name': 'opsgenie_get_oncall',
            'description': 'Get current on-call users for an OpsGenie schedule.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'schedule_id': {
                        'type': 'string',
                        'description': 'Schedule ID or name'
                    },
                    'flat': {
                        'type': 'boolean',
                        'description': 'Return flat list of participants',
                        'default': True
                    },
                    'api_key': {
                        'type': 'string',
                        'description': 'OpsGenie API key'
                    }
                },
                'required': ['schedule_id']
            },
            'handler': opsgenie_get_oncall
        },
        {
            'name': 'opsgenie_escalate_alert',
            'description': 'Escalate an OpsGenie alert to next level.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'alert_id': {
                        'type': 'string',
                        'description': 'Alert identifier'
                    },
                    'escalation_id': {
                        'type': 'string',
                        'description': 'Escalation policy ID or name'
                    },
                    'identifier_type': {
                        'type': 'string',
                        'description': 'Type of identifier',
                        'enum': ['id', 'alias', 'tiny'],
                        'default': 'id'
                    },
                    'user': {
                        'type': 'string',
                        'description': 'User escalating the alert'
                    },
                    'note': {
                        'type': 'string',
                        'description': 'Escalation note'
                    },
                    'api_key': {
                        'type': 'string',
                        'description': 'OpsGenie API key'
                    }
                },
                'required': ['alert_id', 'escalation_id']
            },
            'handler': opsgenie_escalate_alert
        }
    ]
