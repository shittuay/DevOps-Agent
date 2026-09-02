"""
Predictive Scaling Routes for DevOps Agent.

Provides endpoints for predictive scaling recommendations and analysis.
"""

from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user
import logging

from services.predictive_scaling import (
    get_scaling_service, ScalingDirection, ResourceCategory, ConfidenceLevel
)

logger = logging.getLogger(__name__)

scaling_bp = Blueprint('scaling', __name__, url_prefix='/scaling')


# ==================== WEB ROUTES ====================


@scaling_bp.route('/')
@login_required
def scaling_dashboard():
    """Predictive scaling dashboard."""
    service = get_scaling_service()

    # Generate fresh predictions
    predictions = service.generate_all_predictions(current_user.id)
    summary = service.get_summary(current_user.id)

    return render_template('scaling/dashboard.html',
        predictions=predictions,
        summary=summary,
        ScalingDirection=ScalingDirection,
        ConfidenceLevel=ConfidenceLevel
    )


# ==================== API ROUTES ====================


@scaling_bp.route('/api/predictions')
@login_required
def api_list_predictions():
    """API: List scaling predictions."""
    service = get_scaling_service()

    category = request.args.get('category')
    direction = request.args.get('direction')

    if category:
        try:
            category = ResourceCategory(category)
        except ValueError:
            category = None

    if direction:
        try:
            direction = ScalingDirection(direction)
        except ValueError:
            direction = None

    predictions = service.get_predictions(current_user.id, category=category, direction=direction)

    return jsonify({
        'success': True,
        'count': len(predictions),
        'predictions': [{
            'id': p.id,
            'resource_type': p.resource_type,
            'resource_id': p.resource_id,
            'resource_name': p.resource_name,
            'category': p.category.value,
            'direction': p.direction.value,
            'current_capacity': p.current_capacity,
            'recommended_capacity': p.recommended_capacity,
            'predicted_peak': round(p.predicted_peak, 1),
            'predicted_time': p.predicted_time.isoformat(),
            'confidence': p.confidence.value,
            'reasoning': p.reasoning,
            'potential_savings': p.potential_savings,
            'risk_if_ignored': p.risk_if_ignored,
            'created_at': p.created_at.isoformat()
        } for p in predictions]
    })


@scaling_bp.route('/api/analyze', methods=['POST'])
@login_required
def api_analyze():
    """API: Trigger analysis and generate predictions."""
    service = get_scaling_service()

    predictions = service.generate_all_predictions(current_user.id)
    summary = service.get_summary(current_user.id)

    logger.info(f"Scaling analysis run by {current_user.email}: {len(predictions)} predictions")

    return jsonify({
        'success': True,
        'predictions_count': len(predictions),
        'summary': summary
    })


@scaling_bp.route('/api/summary')
@login_required
def api_summary():
    """API: Get scaling recommendations summary."""
    service = get_scaling_service()
    return jsonify({
        'success': True,
        'summary': service.get_summary(current_user.id)
    })


@scaling_bp.route('/api/pattern/<resource_id>')
@login_required
def api_get_pattern(resource_id: str):
    """API: Get detected pattern for a resource."""
    service = get_scaling_service()
    pattern = service.get_pattern(current_user.id, resource_id)

    if not pattern:
        return jsonify({'success': False, 'error': 'No pattern data available'}), 404

    return jsonify({
        'success': True,
        'pattern': {
            'pattern_type': pattern.pattern_type,
            'peak_hours': pattern.peak_hours,
            'peak_days': pattern.peak_days,
            'average_utilization': round(pattern.average_utilization, 1),
            'peak_utilization': round(pattern.peak_utilization, 1),
            'growth_rate': round(pattern.growth_rate, 2)
        }
    })


@scaling_bp.route('/api/metrics/<resource_id>')
@login_required
def api_get_metrics(resource_id: str):
    """API: Get historical metrics for a resource."""
    service = get_scaling_service()
    metrics = service.metrics.get(current_user.id, {}).get(resource_id, [])

    if not metrics:
        return jsonify({'success': False, 'error': 'No metrics available'}), 404

    # Return last 48 hours
    limit = request.args.get('limit', 48, type=int)

    return jsonify({
        'success': True,
        'resource_id': resource_id,
        'data_points': len(metrics),
        'metrics': [{
            'timestamp': m.timestamp.isoformat(),
            'value': round(m.value, 2)
        } for m in metrics[-limit:]]
    })


@scaling_bp.route('/api/apply/<prediction_id>', methods=['POST'])
@login_required
def api_apply_recommendation(prediction_id: str):
    """API: Apply a scaling recommendation."""
    from services.rbac import approver_required, user_is_approver

    # Check if user has approval permission
    if not user_is_approver(current_user):
        return jsonify({
            'success': False,
            'error': 'Approver permission required to apply scaling changes'
        }), 403

    service = get_scaling_service()

    # Find the prediction
    prediction = None
    for p in service.predictions.get(current_user.id, []):
        if p.id == prediction_id:
            prediction = p
            break

    if not prediction:
        return jsonify({'success': False, 'error': 'Prediction not found'}), 404

    # This endpoint does not yet call any AWS/Azure/GCP/Kubernetes API to carry
    # out the scaling change — it must never report success it didn't perform
    # (see CLAUDE.md's "every feature runs against a real cloud account" rule).
    # An approver acting on a false "applied" status would stop looking for
    # other mitigations for a capacity problem that was never actually fixed.
    action_result = {
        'prediction_id': prediction_id,
        'resource_type': prediction.resource_type,
        'resource_id': prediction.resource_id,
        'resource_name': prediction.resource_name,
        'direction': prediction.direction.value,
        'from_capacity': prediction.current_capacity,
        'to_capacity': prediction.recommended_capacity,
        'requested_by': current_user.email,
        'status': 'not_implemented'
    }

    logger.info(f"Scaling apply requested by {current_user.email} for "
                f"{prediction.resource_name}, but no execution path exists yet — refusing "
                f"to report false success")

    return jsonify({
        'success': False,
        'error': 'Applying scaling recommendations is not yet implemented — no cloud API '
                  'call is made. Use the equivalent AWS/Azure/GCP/Kubernetes tool in chat '
                  'to make this change yourself.',
        'action': action_result
    }), 501
