"""
Performance Optimization Routes for DevOps Agent.

Provides API and web UI endpoints for viewing and managing
performance optimization recommendations.
"""

from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user
import logging

from services.performance_optimizer import (
    get_performance_optimizer,
    OptimizationType,
    ResourceType,
    Priority,
    Status
)

logger = logging.getLogger(__name__)

optimization_bp = Blueprint('optimization', __name__, url_prefix='/optimization')


def json_response(data: dict, status: int = 200):
    """Create a JSON response."""
    return jsonify(data), status


@optimization_bp.route('/')
@login_required
def optimization_dashboard():
    """Render the optimization dashboard."""
    optimizer = get_performance_optimizer()
    return render_template(
        'optimization/dashboard.html',
        summary=optimizer.get_summary(current_user.id),
        recommendations=optimizer.get_recommendations(current_user.id, status=Status.PENDING)[:10],
        optimization_types=[t.value for t in OptimizationType],
        resource_types=[r.value for r in ResourceType],
        priorities=[p.value for p in Priority]
    )


@optimization_bp.route('/recommendations')
@login_required
def list_recommendations():
    """Render all recommendations page."""
    optimizer = get_performance_optimizer()

    opt_type = request.args.get('type')
    res_type = request.args.get('resource')
    priority = request.args.get('priority')
    status = request.args.get('status')

    filters = {}
    if opt_type:
        filters['optimization_type'] = OptimizationType(opt_type)
    if res_type:
        filters['resource_type'] = ResourceType(res_type)
    if priority:
        filters['priority'] = Priority(priority)
    if status:
        filters['status'] = Status(status)

    return render_template(
        'optimization/recommendations.html',
        recommendations=optimizer.get_recommendations(current_user.id, **filters),
        summary=optimizer.get_summary(current_user.id),
        optimization_types=[t.value for t in OptimizationType],
        resource_types=[r.value for r in ResourceType],
        priorities=[p.value for p in Priority],
        statuses=[s.value for s in Status],
        current_filters={
            'type': opt_type,
            'resource': res_type,
            'priority': priority,
            'status': status
        }
    )


# API Endpoints

@optimization_bp.route('/api/summary')
@login_required
def api_summary():
    """Get optimization summary."""
    optimizer = get_performance_optimizer()
    return json_response(optimizer.get_summary(current_user.id))


@optimization_bp.route('/api/recommendations', methods=['GET'])
@login_required
def api_list_recommendations():
    """List all recommendations with optional filters."""
    optimizer = get_performance_optimizer()

    opt_type = request.args.get('type')
    res_type = request.args.get('resource')
    priority = request.args.get('priority')
    status = request.args.get('status')

    filters = {}
    try:
        if opt_type:
            filters['optimization_type'] = OptimizationType(opt_type)
        if res_type:
            filters['resource_type'] = ResourceType(res_type)
        if priority:
            filters['priority'] = Priority(priority)
        if status:
            filters['status'] = Status(status)
    except ValueError as e:
        return json_response({"error": f"Invalid filter value: {e}"}, 400)

    return json_response({
        "recommendations": optimizer.get_recommendations(current_user.id, **filters)
    })


@optimization_bp.route('/api/recommendations/<rec_id>', methods=['GET'])
@login_required
def api_get_recommendation(rec_id: str):
    """Get a specific recommendation."""
    optimizer = get_performance_optimizer()
    rec = optimizer.get_recommendation(current_user.id, rec_id)

    if not rec:
        return json_response({"error": "Recommendation not found"}, 404)

    return json_response({"recommendation": rec})


@optimization_bp.route('/api/recommendations/<rec_id>/status', methods=['POST'])
@login_required
def api_update_status(rec_id: str):
    """Update the status of a recommendation."""
    data = request.get_json()

    if not data or 'status' not in data:
        return json_response({"error": "status required"}, 400)

    try:
        new_status = Status(data['status'])
    except ValueError:
        return json_response({"error": "Invalid status"}, 400)

    optimizer = get_performance_optimizer()
    if optimizer.update_recommendation_status(current_user.id, rec_id, new_status):
        return json_response({"success": True, "status": new_status.value})

    return json_response({"error": "Recommendation not found"}, 404)


@optimization_bp.route('/api/recommendations/<rec_id>/dismiss', methods=['POST'])
@login_required
def api_dismiss_recommendation(rec_id: str):
    """Dismiss a recommendation."""
    data = request.get_json() or {}
    reason = data.get('reason')

    optimizer = get_performance_optimizer()
    if optimizer.dismiss_recommendation(current_user.id, rec_id, reason):
        return json_response({"success": True})

    return json_response({"error": "Recommendation not found"}, 404)


@optimization_bp.route('/api/recommendations/<rec_id>/implement', methods=['POST'])
@login_required
def api_implement_recommendation(rec_id: str):
    """Mark a recommendation as implemented."""
    optimizer = get_performance_optimizer()

    rec = optimizer.get_recommendation(current_user.id, rec_id)
    if not rec:
        return json_response({"error": "Recommendation not found"}, 404)

    if not rec.get('auto_fixable'):
        return json_response({
            "error": "This recommendation requires manual implementation",
            "action_steps": rec.get('action_steps', [])
        }, 400)

    if optimizer.update_recommendation_status(current_user.id, rec_id, Status.IMPLEMENTED):
        return json_response({
            "success": True,
            "message": "Recommendation implemented successfully"
        })

    return json_response({"error": "Failed to update status"}, 500)
