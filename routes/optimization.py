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


# ==================== PROACTIVE PREVENTION ENDPOINTS ====================


@optimization_bp.route('/prevention')
@login_required
def prevention_dashboard():
    """Render the proactive prevention dashboard."""
    from models import ProactiveRecommendation
    recs = ProactiveRecommendation.query.filter_by(
        user_id=current_user.id
    ).order_by(ProactiveRecommendation.created_at.desc()).limit(100).all()
    by_category = {}
    for r in recs:
        by_category.setdefault(r.category, []).append(r)
    return render_template(
        'optimization/prevention.html',
        by_category=by_category,
        total=len(recs)
    )


@optimization_bp.route('/api/recommendations/proactive', methods=['GET'])
@login_required
def api_list_proactive():
    """List proactive recommendations with optional filters."""
    from models import ProactiveRecommendation
    category = request.args.get('category')
    status = request.args.get('status')
    q = ProactiveRecommendation.query.filter_by(user_id=current_user.id)
    if category:
        q = q.filter_by(category=category)
    if status:
        q = q.filter_by(status=status)
    recs = q.order_by(ProactiveRecommendation.created_at.desc()).limit(100).all()
    return jsonify({'recommendations': [r.to_dict() for r in recs], 'total': len(recs)})


@optimization_bp.route('/api/recommendations/proactive/analyze', methods=['POST'])
@login_required
def api_run_analysis():
    """Trigger full prevention analysis and save new recommendations."""
    from models import db, ProactiveRecommendation
    from services.prevention_engine import get_prevention_engine
    from flask import current_app
    try:
        engine = get_prevention_engine(app=current_app._get_current_object())
    except Exception:
        engine = get_prevention_engine()

    recs_data = engine.run_full_analysis(current_user.id)
    saved = 0
    for rd in recs_data:
        exists = ProactiveRecommendation.query.filter_by(
            user_id=current_user.id,
            recommendation_type=rd['recommendation_type'],
            status='pending'
        ).first()
        if not exists:
            rec = ProactiveRecommendation(
                user_id=current_user.id,
                category=rd['category'],
                recommendation_type=rd['recommendation_type'],
                title=rd['title'],
                description=rd['description'],
                severity=rd.get('severity', 'medium'),
                affected_resource_ids=rd.get('affected_resource_ids', []),
                source_incident_ids=rd.get('source_incident_ids', []),
                evidence=rd.get('evidence', {}),
                remediation_steps=rd.get('remediation_steps', []),
                estimated_effort=rd.get('estimated_effort', '1d'),
            )
            db.session.add(rec)
            saved += 1
    db.session.commit()
    return jsonify({'success': True, 'analyzed': len(recs_data), 'saved': saved})


@optimization_bp.route('/api/recommendations/<int:rec_id>/agent-spec', methods=['POST'])
@login_required
def api_generate_agent_spec(rec_id):
    """Generate an AI implementation spec for a recommendation."""
    from services.prevention_engine import get_prevention_engine
    from flask import current_app
    try:
        engine = get_prevention_engine(app=current_app._get_current_object())
    except Exception:
        engine = get_prevention_engine()
    spec = engine.generate_agent_spec(rec_id, current_user.id)
    if spec is None:
        return jsonify({'error': 'Recommendation not found or spec generation failed'}), 404
    return jsonify({'success': True, 'spec': spec})


@optimization_bp.route('/api/recommendations/<int:rec_id>/status', methods=['PUT'])
@login_required
def api_update_rec_status(rec_id):
    """Update the status of a proactive recommendation."""
    from models import db, ProactiveRecommendation
    rec = ProactiveRecommendation.query.filter_by(
        id=rec_id, user_id=current_user.id
    ).first()
    if not rec:
        return jsonify({'error': 'Recommendation not found'}), 404
    data = request.get_json() or {}
    new_status = data.get('status', rec.status)
    allowed = {'pending', 'in_progress', 'resolved', 'dismissed'}
    if new_status not in allowed:
        return jsonify({'error': f'Invalid status. Allowed: {allowed}'}), 400
    rec.status = new_status
    db.session.commit()
    return jsonify({'success': True, 'status': new_status})
