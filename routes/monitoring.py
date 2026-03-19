"""
Proactive Monitoring Routes for DevOps Agent.

Provides API and web UI endpoints for managing monitoring rules and alerts.
All rules and alerts are scoped to the current user.
"""

from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user
import logging

from services.proactive_monitoring import (
    get_monitoring_service,
    MonitoringRuleState,
    MetricSource,
    AlertCondition
)

logger = logging.getLogger(__name__)

monitoring_bp = Blueprint('monitoring', __name__, url_prefix='/monitoring')


def json_response(data: dict, status: int = 200):
    return jsonify(data), status


@monitoring_bp.route('/')
@login_required
def monitoring_dashboard():
    service = get_monitoring_service()
    uid = current_user.id
    rules = service.get_rules(uid)
    user_monitoring_active = any(r.get('enabled') for r in rules)
    return render_template(
        'monitoring/dashboard.html',
        status=service.get_status(uid),
        rules=rules,
        alerts=service.get_active_alerts(uid),
        sources=[s.value for s in MetricSource],
        conditions=[c.value for c in AlertCondition],
        user_monitoring_active=user_monitoring_active,
    )


@monitoring_bp.route('/rules')
@login_required
def list_rules():
    service = get_monitoring_service()
    uid = current_user.id
    return render_template(
        'monitoring/rules.html',
        rules=service.get_rules(uid),
        sources=[s.value for s in MetricSource],
        conditions=[c.value for c in AlertCondition]
    )


@monitoring_bp.route('/alerts')
@login_required
def list_alerts():
    service = get_monitoring_service()
    uid = current_user.id
    return render_template(
        'monitoring/alerts.html',
        active_alerts=service.get_active_alerts(uid),
        alert_history=service.get_alert_history(uid, limit=50)
    )


# API Endpoints

@monitoring_bp.route('/api/status')
@login_required
def api_status():
    service = get_monitoring_service()
    return json_response(service.get_status(current_user.id))


@monitoring_bp.route('/api/rules', methods=['GET'])
@login_required
def api_list_rules():
    service = get_monitoring_service()
    return json_response({"rules": service.get_rules(current_user.id)})


@monitoring_bp.route('/api/rules', methods=['POST'])
@login_required
def api_create_rule():
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

    try:
        threshold = float(data['threshold'])
    except (ValueError, TypeError):
        return json_response({"error": "threshold must be a numeric value"}, 400)

    import uuid
    rule = MonitoringRuleState(
        id=data.get('id', str(uuid.uuid4())[:8]),
        name=data['name'],
        description=data.get('description', ''),
        source=source,
        query=data['query'],
        condition=condition,
        threshold=threshold,
        duration_seconds=int(data.get('duration_seconds', 60)),
        severity=data.get('severity', 'medium'),
        labels=data.get('labels', {}),
        enabled=data.get('enabled', True),
        check_interval_seconds=int(data.get('check_interval_seconds', 30))
    )

    service = get_monitoring_service()
    rule_id = service.add_rule(current_user.id, rule)
    return json_response({"success": True, "rule_id": rule_id})


@monitoring_bp.route('/api/rules/<rule_id>', methods=['GET'])
@login_required
def api_get_rule(rule_id: str):
    service = get_monitoring_service()
    uid = current_user.id
    service._ensure_user_loaded(uid)
    rules = service._user_rules.get(uid, {})
    if rule_id not in rules:
        return json_response({"error": "Rule not found"}, 404)
    return json_response({"rule": rules[rule_id].to_dict()})


@monitoring_bp.route('/api/rules/<rule_id>', methods=['DELETE'])
@login_required
def api_delete_rule(rule_id: str):
    service = get_monitoring_service()
    if service.remove_rule(current_user.id, rule_id):
        return json_response({"success": True})
    return json_response({"error": "Rule not found"}, 404)


@monitoring_bp.route('/api/rules/<rule_id>/enable', methods=['POST'])
@login_required
def api_enable_rule(rule_id: str):
    service = get_monitoring_service()
    if service.enable_rule(current_user.id, rule_id):
        return json_response({"success": True, "enabled": True})
    return json_response({"error": "Rule not found"}, 404)


@monitoring_bp.route('/api/rules/<rule_id>/disable', methods=['POST'])
@login_required
def api_disable_rule(rule_id: str):
    service = get_monitoring_service()
    if service.disable_rule(current_user.id, rule_id):
        return json_response({"success": True, "enabled": False})
    return json_response({"error": "Rule not found"}, 404)


@monitoring_bp.route('/api/rules/<rule_id>/check', methods=['POST'])
@login_required
def api_check_rule(rule_id: str):
    service = get_monitoring_service()
    uid = current_user.id
    service._ensure_user_loaded(uid)
    rules = service._user_rules.get(uid, {})
    if rule_id not in rules:
        return json_response({"error": "Rule not found"}, 404)
    result = service.check_now(uid, rule_id)
    return json_response({"success": True, "result": result.get(rule_id, {})})


@monitoring_bp.route('/api/alerts', methods=['GET'])
@login_required
def api_list_alerts():
    service = get_monitoring_service()
    uid = current_user.id
    return json_response({
        "active": service.get_active_alerts(uid),
        "history": service.get_alert_history(uid, limit=50)
    })


@monitoring_bp.route('/api/alerts/<alert_id>/acknowledge', methods=['POST'])
@login_required
def api_acknowledge_alert(alert_id: str):
    service = get_monitoring_service()
    if service.acknowledge_alert(current_user.id, alert_id, current_user.email):
        return json_response({"success": True})
    return json_response({"error": "Alert not found"}, 404)


@monitoring_bp.route('/api/service/start', methods=['POST'])
@login_required
def api_start_service():
    """Enable all monitoring rules for the current user."""
    service = get_monitoring_service()
    uid = current_user.id
    service.enable_all_rules(uid)
    return json_response({"success": True, "running": True})


@monitoring_bp.route('/api/service/stop', methods=['POST'])
@login_required
def api_stop_service():
    """Disable all monitoring rules for the current user."""
    service = get_monitoring_service()
    uid = current_user.id
    service.disable_all_rules(uid)
    return json_response({"success": True, "running": False})


@monitoring_bp.route('/api/check-all', methods=['POST'])
@login_required
def api_check_all():
    service = get_monitoring_service()
    results = service.check_now(current_user.id)
    return json_response({"success": True, "results": results})
