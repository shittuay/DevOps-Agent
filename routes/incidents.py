"""
Incident Response API routes for DevOps Agent.
All engine methods receive user_id for per-user isolation.
"""

from flask import Blueprint, request, jsonify, render_template, make_response, flash, redirect, url_for
from flask_login import login_required, current_user
from services.incident_response import (
    get_incident_engine, IncidentSeverity, IncidentStatus,
    ResponsePlaybook, RemediationAction, ActionType, BUILTIN_IDS
)
from services.rbac import require_permission, Permission, approver_required
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

incidents_bp = Blueprint('incidents', __name__, url_prefix='/incidents')


# ==================== WEB ROUTES ====================


@incidents_bp.route('/')
@login_required
def incidents_dashboard():
    """Incident response dashboard."""
    engine = get_incident_engine()
    user_id = current_user.id

    incidents = engine.list_incidents(user_id, limit=50)
    playbooks = engine.list_playbooks(user_id)
    stats = engine.get_stats(user_id)

    return render_template('incidents/dashboard.html',
        incidents=incidents,
        playbooks=playbooks,
        stats=stats,
        IncidentStatus=IncidentStatus,
        IncidentSeverity=IncidentSeverity
    )


@incidents_bp.route('/<incident_id>')
@login_required
def view_incident(incident_id):
    """View incident details."""
    engine = get_incident_engine()
    user_id = current_user.id
    incident = engine.get_incident(user_id, incident_id)

    if not incident:
        flash('Incident not found', 'error')
        return redirect(url_for('incidents.incidents_dashboard'))

    playbook = None
    if incident.playbook_id:
        playbook = engine.get_playbook(user_id, incident.playbook_id)

    resp = make_response(render_template('incidents/detail.html',
        incident=incident,
        playbook=playbook,
        IncidentStatus=IncidentStatus
    ))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp


@incidents_bp.route('/playbooks')
@login_required
def list_playbooks():
    """List all playbooks."""
    from services.rbac import user_is_approver

    engine = get_incident_engine()
    user_id = current_user.id
    playbooks = engine.list_playbooks(user_id)

    return render_template('incidents/playbooks.html',
        playbooks=playbooks,
        can_create=user_is_approver(current_user)
    )


@incidents_bp.route('/playbooks/new')
@login_required
@approver_required
def new_playbook():
    """Create new playbook form."""
    return render_template('incidents/playbook_builder.html', playbook=None)


@incidents_bp.route('/playbooks/<playbook_id>/edit')
@login_required
@approver_required
def edit_playbook(playbook_id):
    """Edit playbook form."""
    engine = get_incident_engine()
    user_id = current_user.id
    playbook = engine.get_playbook(user_id, playbook_id)

    if not playbook:
        return jsonify({'error': 'Playbook not found'}), 404

    return render_template('incidents/playbook_builder.html', playbook=playbook)


# ==================== API ROUTES ====================


@incidents_bp.route('/api/list')
@login_required
def api_list_incidents():
    """API: List incidents."""
    engine = get_incident_engine()
    user_id = current_user.id

    status_filter = request.args.get('status')
    severity_filter = request.args.get('severity')
    limit = request.args.get('limit', 50, type=int)

    status = None
    if status_filter:
        try:
            status = IncidentStatus(status_filter)
        except ValueError:
            pass

    severity = None
    if severity_filter:
        try:
            severity = IncidentSeverity(severity_filter)
        except ValueError:
            pass

    incidents = engine.list_incidents(user_id, status=status, severity=severity, limit=limit)

    return jsonify({
        'success': True,
        'count': len(incidents),
        'incidents': [{
            'id': i.id,
            'title': i.title,
            'severity': i.severity.value,
            'status': i.status.value,
            'source': i.source,
            'triggered_at': i.triggered_at.isoformat(),
            'acknowledged_at': i.acknowledged_at.isoformat() if i.acknowledged_at else None,
            'resolved_at': i.resolved_at.isoformat() if i.resolved_at else None,
            'assigned_to': i.assigned_to,
            'playbook_id': i.playbook_id
        } for i in incidents]
    })


@incidents_bp.route('/api/<incident_id>')
@login_required
def api_get_incident(incident_id):
    """API: Get incident details."""
    engine = get_incident_engine()
    user_id = current_user.id
    incident = engine.get_incident(user_id, incident_id)

    if not incident:
        return jsonify({'success': False, 'error': 'Incident not found'}), 404

    return jsonify({
        'success': True,
        'incident': {
            'id': incident.id,
            'title': incident.title,
            'description': incident.description,
            'severity': incident.severity.value,
            'status': incident.status.value,
            'source': incident.source,
            'source_id': incident.source_id,
            'playbook_id': incident.playbook_id,
            'triggered_at': incident.triggered_at.isoformat(),
            'acknowledged_at': incident.acknowledged_at.isoformat() if incident.acknowledged_at else None,
            'resolved_at': incident.resolved_at.isoformat() if incident.resolved_at else None,
            'assigned_to': incident.assigned_to,
            'metadata': incident.metadata,
            'actions_taken': incident.actions_taken,
            'timeline': incident.timeline
        }
    })


@incidents_bp.route('/api/<incident_id>/acknowledge', methods=['POST'])
@login_required
def api_acknowledge_incident(incident_id):
    """API: Acknowledge an incident."""
    engine = get_incident_engine()
    user_id = current_user.id

    result = engine.acknowledge_incident(user_id, incident_id, user=current_user.email)

    if result['success']:
        logger.info(f"Incident {incident_id} acknowledged by {current_user.email}")

    return jsonify(result)


@incidents_bp.route('/api/<incident_id>/resolve', methods=['POST'])
@login_required
def api_resolve_incident(incident_id):
    """API: Resolve an incident."""
    engine = get_incident_engine()
    user_id = current_user.id

    data = request.get_json(silent=True) or {}
    resolution = data.get('resolution', f'Resolved by {current_user.email}')

    result = engine.resolve_incident(user_id, incident_id, resolution)

    if result['success']:
        logger.info(f"Incident {incident_id} resolved by {current_user.email}")

    return jsonify(result)


@incidents_bp.route('/api/<incident_id>/execute', methods=['POST'])
@login_required
@approver_required
def api_execute_playbook(incident_id):
    """API: Execute playbook for an incident (requires approver role)."""
    try:
        engine = get_incident_engine()
        user_id = current_user.id
        incident = engine.get_incident(user_id, incident_id)

        if not incident:
            return jsonify({'success': False, 'error': 'Incident not found'}), 404

        data = request.get_json(silent=True) or {}
        skip_approval = data.get('skip_approval', False)

        from services.rbac import user_is_admin
        if skip_approval and not user_is_admin(current_user):
            skip_approval = False

        result = engine.execute_playbook(user_id, incident, skip_approval=skip_approval)

        logger.info(
            f"Playbook executed for incident {incident_id} by {current_user.email}, "
            f"skip_approval={skip_approval}"
        )

        return jsonify(result)
    except Exception as e:
        logger.error(f"Playbook execution error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@incidents_bp.route('/api/process', methods=['POST'])
@login_required
def api_process_alert():
    """API: Process an incoming alert (creates incident if needed)."""
    data = request.get_json()

    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    engine = get_incident_engine()
    user_id = current_user.id
    incident = engine.process_alert(user_id, data)

    if incident:
        logger.info(f"Alert processed, created incident {incident.id}")
        return jsonify({
            'success': True,
            'incident_id': incident.id,
            'playbook_matched': incident.playbook_id is not None,
            'status': incident.status.value
        })

    return jsonify({'success': False, 'error': 'Failed to process alert'}), 500


@incidents_bp.route('/api/stats')
@login_required
def api_stats():
    """API: Get incident statistics."""
    engine = get_incident_engine()
    user_id = current_user.id
    return jsonify({
        'success': True,
        'stats': engine.get_stats(user_id)
    })


@incidents_bp.route('/api/playbooks')
@login_required
def api_list_playbooks():
    """API: List all playbooks."""
    engine = get_incident_engine()
    user_id = current_user.id
    playbooks = engine.list_playbooks(user_id)

    return jsonify({
        'success': True,
        'count': len(playbooks),
        'playbooks': [{
            'id': p.id,
            'name': p.name,
            'description': p.description,
            'severity': p.severity.value,
            'enabled': p.enabled,
            'auto_execute': p.auto_execute,
            'actions_count': len(p.actions),
            'tags': p.tags,
            'is_builtin': p.is_builtin,
        } for p in playbooks]
    })


@incidents_bp.route('/api/playbooks/<playbook_id>')
@login_required
def api_get_playbook(playbook_id):
    """API: Get playbook details."""
    engine = get_incident_engine()
    user_id = current_user.id
    playbook = engine.get_playbook(user_id, playbook_id)

    if not playbook:
        return jsonify({'success': False, 'error': 'Playbook not found'}), 404

    return jsonify({
        'success': True,
        'playbook': {
            'id': playbook.id,
            'name': playbook.name,
            'description': playbook.description,
            'trigger_conditions': playbook.trigger_conditions,
            'severity': playbook.severity.value,
            'enabled': playbook.enabled,
            'auto_execute': playbook.auto_execute,
            'notification_channels': playbook.notification_channels,
            'escalation_policy': playbook.escalation_policy,
            'tags': playbook.tags,
            'is_builtin': playbook.is_builtin,
            'actions': [{
                'name': a.name,
                'type': a.action_type.value,
                'description': a.description,
                'requires_approval': a.requires_approval,
                'parameters': a.parameters
            } for a in playbook.actions]
        }
    })


@incidents_bp.route('/api/playbooks/<playbook_id>/toggle', methods=['POST'])
@login_required
@approver_required
def api_toggle_playbook(playbook_id):
    """API: Enable/disable a playbook."""
    engine = get_incident_engine()
    user_id = current_user.id
    new_state = engine.toggle_playbook(user_id, playbook_id)

    if new_state is None:
        return jsonify({'success': False, 'error': 'Playbook not found'}), 404

    logger.info(
        f"Playbook {playbook_id} {'enabled' if new_state else 'disabled'} "
        f"by {current_user.email}"
    )

    return jsonify({
        'success': True,
        'playbook_id': playbook_id,
        'enabled': new_state
    })


# Webhook endpoint for external alerting systems
@incidents_bp.route('/webhook/<source>', methods=['POST'])
def webhook_receive(source):
    """
    Webhook endpoint for receiving alerts from external systems.
    Supports: prometheus, alertmanager, datadog, pagerduty, opsgenie, grafana
    Note: Webhooks use a system user_id since there's no authenticated user.
    """
    valid_sources = {'prometheus', 'alertmanager', 'datadog', 'pagerduty', 'opsgenie', 'grafana'}
    if source not in valid_sources:
        return jsonify({'error': 'Unsupported webhook source'}), 400

    data = request.get_json()

    if not data:
        return jsonify({'error': 'No data'}), 400

    alert_data = _transform_webhook_data(source, data)

    if alert_data:
        engine = get_incident_engine()
        # Webhook alerts default to admin user (id=1) — user_id is NOT accepted from external input
        user_id = 1
        incident = engine.process_alert(user_id, alert_data)

        if incident:
            return jsonify({
                'status': 'ok',
                'incident_id': incident.id
            })

    return jsonify({'status': 'ignored'})


def _transform_webhook_data(source: str, data: dict) -> dict:
    """Transform webhook data from various sources to standard format."""

    if source == 'prometheus' or source == 'alertmanager':
        alerts = data.get('alerts', [data])
        if alerts:
            alert = alerts[0]
            labels = alert.get('labels', {})
            return {
                'source': 'prometheus',
                'alert_name': labels.get('alertname', 'Unknown'),
                'title': alert.get('annotations', {}).get('summary', labels.get('alertname')),
                'description': alert.get('annotations', {}).get('description', ''),
                'severity': labels.get('severity', 'warning'),
                'status': alert.get('status', 'firing'),
                'instance': labels.get('instance', ''),
                'job': labels.get('job', ''),
                'namespace': labels.get('namespace', ''),
            }

    elif source == 'datadog':
        return {
            'source': 'datadog',
            'alert_name': data.get('alert_title', 'Datadog Alert'),
            'title': data.get('alert_title', ''),
            'description': data.get('alert_body', ''),
            'severity': _map_datadog_priority(data.get('priority', 'normal')),
            'alert_id': data.get('alert_id'),
            'monitor_id': data.get('monitor_id'),
            'tags': data.get('tags', []),
        }

    elif source == 'pagerduty':
        messages = data.get('messages', [data])
        if messages:
            msg = messages[0]
            incident = msg.get('incident', {})
            return {
                'source': 'pagerduty',
                'alert_name': incident.get('title', 'PagerDuty Incident'),
                'title': incident.get('title', ''),
                'description': incident.get('description', ''),
                'severity': _map_pd_urgency(incident.get('urgency', 'high')),
                'alert_id': incident.get('id'),
                'service': incident.get('service', {}).get('name')
            }

    elif source == 'opsgenie':
        alert = data.get('alert', data)
        return {
            'source': 'opsgenie',
            'alert_name': alert.get('message', 'OpsGenie Alert'),
            'title': alert.get('message', ''),
            'description': alert.get('description', ''),
            'severity': _map_opsgenie_priority(alert.get('priority', 'P3')),
            'alert_id': alert.get('alertId'),
            'tags': alert.get('tags', [])
        }

    elif source == 'grafana':
        return {
            'source': 'grafana',
            'alert_name': data.get('ruleName', 'Grafana Alert'),
            'title': data.get('title', data.get('ruleName', '')),
            'description': data.get('message', ''),
            'severity': data.get('state', 'alerting'),
            'alert_id': data.get('ruleId')
        }

    return {
        'source': source,
        'alert_name': data.get('alert_name') or data.get('title', 'Unknown'),
        'title': data.get('title', ''),
        'description': data.get('description', ''),
        'severity': data.get('severity', 'medium'),
    }


def _map_datadog_priority(priority: str) -> str:
    mapping = {'normal': 'medium', 'low': 'low'}
    return mapping.get(priority, 'medium')


def _map_pd_urgency(urgency: str) -> str:
    mapping = {'high': 'critical', 'low': 'low'}
    return mapping.get(urgency, 'high')


def _map_opsgenie_priority(priority: str) -> str:
    mapping = {
        'P1': 'critical',
        'P2': 'high',
        'P3': 'medium',
        'P4': 'low',
        'P5': 'info'
    }
    return mapping.get(priority, 'medium')


# ==================== PLAYBOOK CRUD API ====================


@incidents_bp.route('/api/playbooks', methods=['POST'])
@login_required
@approver_required
def api_create_playbook():
    """API: Create a new playbook."""
    data = request.get_json()

    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    if not data.get('name'):
        return jsonify({'success': False, 'error': 'Playbook name is required'}), 400

    if not data.get('actions'):
        return jsonify({'success': False, 'error': 'At least one action is required'}), 400

    engine = get_incident_engine()
    user_id = current_user.id

    import uuid
    playbook_id = data.get('id') or f"custom-{str(uuid.uuid4())[:8]}"

    if engine.get_playbook(user_id, playbook_id):
        playbook_id = f"custom-{str(uuid.uuid4())[:8]}"

    try:
        severity = IncidentSeverity(data.get('severity', 'medium'))
    except ValueError:
        severity = IncidentSeverity.MEDIUM

    actions = []
    for action_data in data.get('actions', []):
        try:
            action_type = ActionType(action_data.get('action_type', 'custom'))
        except ValueError:
            action_type = ActionType.CUSTOM

        actions.append(RemediationAction(
            action_type=action_type,
            name=action_data.get('name', 'Unnamed Action'),
            description=action_data.get('description', ''),
            parameters=action_data.get('parameters', {}),
            requires_approval=action_data.get('requires_approval', False),
            timeout_seconds=action_data.get('timeout_seconds', 300)
        ))

    playbook = ResponsePlaybook(
        id=playbook_id,
        name=data.get('name'),
        description=data.get('description', ''),
        trigger_conditions=data.get('trigger_conditions', {}),
        severity=severity,
        actions=actions,
        enabled=data.get('enabled', True),
        auto_execute=data.get('auto_execute', False),
        notification_channels=data.get('notification_channels', []),
        escalation_policy=data.get('escalation_policy'),
        tags=data.get('tags', [])
    )

    engine.register_playbook(user_id, playbook)

    logger.info(f"Playbook '{playbook.name}' created by {current_user.email}")

    return jsonify({
        'success': True,
        'playbook_id': playbook_id,
        'message': 'Playbook created successfully'
    })


@incidents_bp.route('/api/playbooks/<playbook_id>', methods=['PUT'])
@login_required
@approver_required
def api_update_playbook(playbook_id):
    """API: Update an existing playbook."""
    engine = get_incident_engine()
    user_id = current_user.id
    playbook = engine.get_playbook(user_id, playbook_id)

    if not playbook:
        return jsonify({'success': False, 'error': 'Playbook not found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    if 'name' in data:
        playbook.name = data['name']
    if 'description' in data:
        playbook.description = data['description']
    if 'severity' in data:
        try:
            playbook.severity = IncidentSeverity(data['severity'])
        except ValueError:
            pass
    if 'trigger_conditions' in data:
        playbook.trigger_conditions = data['trigger_conditions']
    if 'enabled' in data:
        playbook.enabled = data['enabled']
    if 'auto_execute' in data:
        playbook.auto_execute = data['auto_execute']
    if 'notification_channels' in data:
        playbook.notification_channels = data['notification_channels']
    if 'escalation_policy' in data:
        playbook.escalation_policy = data['escalation_policy']
    if 'tags' in data:
        playbook.tags = data['tags']

    if 'actions' in data:
        actions = []
        for action_data in data['actions']:
            try:
                action_type = ActionType(action_data.get('action_type', 'custom'))
            except ValueError:
                action_type = ActionType.CUSTOM

            actions.append(RemediationAction(
                action_type=action_type,
                name=action_data.get('name', 'Unnamed Action'),
                description=action_data.get('description', ''),
                parameters=action_data.get('parameters', {}),
                requires_approval=action_data.get('requires_approval', False),
                timeout_seconds=action_data.get('timeout_seconds', 300)
            ))
        playbook.actions = actions

    playbook.updated_at = datetime.utcnow()
    engine.register_playbook(user_id, playbook)

    logger.info(f"Playbook '{playbook.name}' updated by {current_user.email}")

    return jsonify({
        'success': True,
        'playbook_id': playbook_id,
        'message': 'Playbook updated successfully'
    })


@incidents_bp.route('/api/playbooks/<playbook_id>', methods=['DELETE'])
@login_required
@approver_required
def api_delete_playbook(playbook_id):
    """API: Delete a playbook."""
    engine = get_incident_engine()
    user_id = current_user.id
    playbook = engine.get_playbook(user_id, playbook_id)

    if not playbook:
        return jsonify({'success': False, 'error': 'Playbook not found'}), 404

    if playbook_id in BUILTIN_IDS:
        return jsonify({
            'success': False,
            'error': 'Cannot delete built-in playbooks. You can disable them instead.'
        }), 400

    engine.unregister_playbook(user_id, playbook_id)

    logger.info(f"Playbook '{playbook.name}' deleted by {current_user.email}")

    return jsonify({
        'success': True,
        'message': 'Playbook deleted successfully'
    })


# ==================== JOURNAL & CORRELATION ENDPOINTS ====================


@incidents_bp.route('/api/incidents/groups', methods=['GET'])
@login_required
def api_incident_groups():
    """List all correlation groups for the current user."""
    from models import IncidentCorrelationGroup
    groups = IncidentCorrelationGroup.query.filter_by(
        user_id=current_user.id
    ).order_by(IncidentCorrelationGroup.created_at.desc()).limit(50).all()
    return jsonify({'groups': [g.to_dict() for g in groups]})


@incidents_bp.route('/api/incidents/<incident_id>/journal', methods=['GET'])
@login_required
def api_incident_journal(incident_id):
    """List journal entries for an incident."""
    from models import InvestigationJournalEntry, IncidentModel
    # Verify ownership
    row = IncidentModel.query.filter_by(
        incident_key=incident_id, user_id=current_user.id
    ).first()
    if not row:
        return jsonify({'error': 'Incident not found'}), 404
    entries = InvestigationJournalEntry.query.filter_by(
        user_id=current_user.id,
        incident_key=incident_id
    ).order_by(InvestigationJournalEntry.created_at.asc()).all()
    return jsonify({'entries': [e.to_dict() for e in entries]})


@incidents_bp.route('/api/incidents/<incident_id>/journal', methods=['POST'])
@login_required
def api_add_journal_note(incident_id):
    """Add a manual note to the incident journal."""
    from models import db, InvestigationJournalEntry, IncidentModel
    row = IncidentModel.query.filter_by(
        incident_key=incident_id, user_id=current_user.id
    ).first()
    if not row:
        return jsonify({'error': 'Incident not found'}), 404
    data = request.get_json() or {}
    content = data.get('content', '').strip()
    if not content:
        return jsonify({'error': 'content is required'}), 400
    entry = InvestigationJournalEntry(
        user_id=current_user.id,
        incident_key=incident_id,
        entry_type='note',
        content=content,
        author='user',
    )
    db.session.add(entry)
    db.session.commit()
    return jsonify(entry.to_dict()), 201


@incidents_bp.route('/api/incidents/<incident_id>/related', methods=['GET'])
@login_required
def api_incident_related(incident_id):
    """Get incidents sharing the same correlation group."""
    from models import IncidentModel
    row = IncidentModel.query.filter_by(
        incident_key=incident_id, user_id=current_user.id
    ).first()
    if not row:
        return jsonify({'error': 'Incident not found'}), 404
    related = []
    if row.correlation_group_key:
        related_rows = IncidentModel.query.filter_by(
            user_id=current_user.id,
            correlation_group_key=row.correlation_group_key
        ).filter(IncidentModel.incident_key != incident_id).limit(20).all()
        related = [r.to_dict() for r in related_rows]
    return jsonify({'related': related, 'correlation_group_key': row.correlation_group_key})
