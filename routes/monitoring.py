"""
Proactive Monitoring Routes for DevOps Agent.

Provides API and web UI endpoints for managing monitoring rules and alerts.
"""

from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user
from functools import wraps
import logging

from services.proactive_monitoring import (
    get_monitoring_service,
    MonitoringRule,
    MetricSource,
    AlertCondition
)

logger = logging.getLogger(__name__)

monitoring_bp = Blueprint('monitoring', __name__, url_prefix='/monitoring')


def json_response(data: dict, status: int = 200):
    """Create a JSON response."""
    return jsonify(data), status


@monitoring_bp.route('/')
@login_required
def monitoring_dashboard():
    """Render the monitoring dashboard."""
    service = get_monitoring_service()
    return render_template(
        'monitoring/dashboard.html',
        status=service.get_status(),
        rules=service.get_rules(),
        alerts=service.get_active_alerts(),
        sources=[s.value for s in MetricSource],
        conditions=[c.value for c in AlertCondition]
    )


@monitoring_bp.route('/rules')
@login_required
def list_rules():
    """Render the rules list page."""
    service = get_monitoring_service()
    return render_template(
        'monitoring/rules.html',
        rules=service.get_rules(),
        sources=[s.value for s in MetricSource],
        conditions=[c.value for c in AlertCondition]
    )


@monitoring_bp.route('/alerts')
@login_required
def list_alerts():
    """Render the alerts page."""
    service = get_monitoring_service()
    return render_template(
        'monitoring/alerts.html',
        active_alerts=service.get_active_alerts(),
        alert_history=service.get_alert_history(limit=50)
    )


# API Endpoints

@monitoring_bp.route('/api/status')
@login_required
def api_status():
    """Get monitoring service status."""
    service = get_monitoring_service()
    return json_response(service.get_status())


@monitoring_bp.route('/api/rules', methods=['GET'])
@login_required
def api_list_rules():
    """List all monitoring rules."""
    service = get_monitoring_service()
    return json_response({"rules": service.get_rules()})


@monitoring_bp.route('/api/rules', methods=['POST'])
@login_required
def api_create_rule():
    """Create a new monitoring rule."""
    data = request.get_json()

    if not data:
        return json_response({"error": "No data provided"}, 400)

    required = ['name', 'query', 'threshold']
    missing = [f for f in required if f not in data]
    if missing:
        return json_response({"error": f"Missing fields: {missing}"}, 400)

    try:
        source = MetricSource(data.get('source', 'prometheus'))
        condition = AlertCondition(data.get('condition', 'gt'))
    except ValueError as e:
        return json_response({"error": str(e)}, 400)

    import uuid
    rule = MonitoringRule(
        id=data.get('id', str(uuid.uuid4())[:8]),
        name=data['name'],
        description=data.get('description', ''),
        source=source,
        query=data['query'],
        condition=condition,
        threshold=float(data['threshold']),
        duration_seconds=int(data.get('duration_seconds', 60)),
        severity=data.get('severity', 'medium'),
        labels=data.get('labels', {}),
        enabled=data.get('enabled', True),
        check_interval_seconds=int(data.get('check_interval_seconds', 30))
    )

    service = get_monitoring_service()
    rule_id = service.add_rule(rule)

    return json_response({"success": True, "rule_id": rule_id})


@monitoring_bp.route('/api/rules/<rule_id>', methods=['GET'])
@login_required
def api_get_rule(rule_id: str):
    """Get a specific monitoring rule."""
    service = get_monitoring_service()

    if rule_id not in service.rules:
        return json_response({"error": "Rule not found"}, 404)

    return json_response({"rule": service.rules[rule_id].to_dict()})


@monitoring_bp.route('/api/rules/<rule_id>', methods=['DELETE'])
@login_required
def api_delete_rule(rule_id: str):
    """Delete a monitoring rule."""
    service = get_monitoring_service()

    if service.remove_rule(rule_id):
        return json_response({"success": True})
    return json_response({"error": "Rule not found"}, 404)


@monitoring_bp.route('/api/rules/<rule_id>/enable', methods=['POST'])
@login_required
def api_enable_rule(rule_id: str):
    """Enable a monitoring rule."""
    service = get_monitoring_service()

    if service.enable_rule(rule_id):
        return json_response({"success": True, "enabled": True})
    return json_response({"error": "Rule not found"}, 404)


@monitoring_bp.route('/api/rules/<rule_id>/disable', methods=['POST'])
@login_required
def api_disable_rule(rule_id: str):
    """Disable a monitoring rule."""
    service = get_monitoring_service()

    if service.disable_rule(rule_id):
        return json_response({"success": True, "enabled": False})
    return json_response({"error": "Rule not found"}, 404)


@monitoring_bp.route('/api/rules/<rule_id>/check', methods=['POST'])
@login_required
def api_check_rule(rule_id: str):
    """Immediately check a specific rule."""
    service = get_monitoring_service()

    if rule_id not in service.rules:
        return json_response({"error": "Rule not found"}, 404)

    result = service.check_now(rule_id)
    return json_response({"success": True, "result": result.get(rule_id, {})})


@monitoring_bp.route('/api/alerts', methods=['GET'])
@login_required
def api_list_alerts():
    """List all active alerts."""
    service = get_monitoring_service()
    return json_response({
        "active": service.get_active_alerts(),
        "history": service.get_alert_history(limit=50)
    })


@monitoring_bp.route('/api/alerts/<alert_id>/acknowledge', methods=['POST'])
@login_required
def api_acknowledge_alert(alert_id: str):
    """Acknowledge an alert."""
    service = get_monitoring_service()

    if service.acknowledge_alert(alert_id, current_user.email):
        return json_response({"success": True})
    return json_response({"error": "Alert not found"}, 404)


@monitoring_bp.route('/api/service/start', methods=['POST'])
@login_required
def api_start_service():
    """Start the monitoring service."""
    service = get_monitoring_service()

    if service.is_running():
        return json_response({"error": "Service already running"}, 400)

    service.start()
    return json_response({"success": True, "running": True})


@monitoring_bp.route('/api/service/stop', methods=['POST'])
@login_required
def api_stop_service():
    """Stop the monitoring service."""
    service = get_monitoring_service()

    if not service.is_running():
        return json_response({"error": "Service not running"}, 400)

    service.stop()
    return json_response({"success": True, "running": False})


@monitoring_bp.route('/api/check-all', methods=['POST'])
@login_required
def api_check_all():
    """Immediately check all rules."""
    service = get_monitoring_service()
    results = service.check_now()
    return json_response({"success": True, "results": results})
