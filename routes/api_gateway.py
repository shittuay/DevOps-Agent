"""
API Gateway Routes
"""
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from functools import wraps
import time

api_gateway_bp = Blueprint('api_gateway', __name__, url_prefix='/api-gateway')


def api_key_required(f):
    """Decorator to validate API key for external API endpoints"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from services.api_gateway import APIGatewayService

        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        if not api_key:
            return jsonify({'error': 'API key required'}), 401

        service = APIGatewayService()
        key_record = service.get_api_key_by_key(api_key)

        if not key_record:
            return jsonify({'error': 'Invalid API key'}), 401

        allowed, _ = service.check_rate_limit(key_record)
        if not allowed:
            return jsonify({'error': 'Rate limit exceeded'}), 429

        request.api_key = key_record
        return f(*args, **kwargs)
    return decorated_function


# Dashboard routes
@api_gateway_bp.route('/')
@login_required
def dashboard():
    """API Gateway dashboard"""
    return render_template('api_gateway/dashboard.html')


@api_gateway_bp.route('/keys')
@login_required
def list_keys():
    """List API keys"""
    from services.api_gateway import APIGatewayService
    service = APIGatewayService()
    keys = service.get_user_api_keys(current_user.id)
    return render_template('api_gateway/keys.html', keys=keys)


@api_gateway_bp.route('/keys/create', methods=['GET', 'POST'])
@login_required
def create_key():
    """Create new API key"""
    if request.method == 'POST':
        from services.api_gateway import APIGatewayService
        service = APIGatewayService()

        try:
            rate_limit = max(1, min(int(request.form.get('rate_limit', 1000)), 100000))
        except (ValueError, TypeError):
            rate_limit = 1000
        try:
            expires_days = max(0, min(int(request.form.get('expires_days', 0)), 365))
        except (ValueError, TypeError):
            expires_days = 0

        name = (request.form.get('name') or '')[:100]
        data = {
            'user_id': current_user.id,
            'name': name,
            'scopes': request.form.getlist('scopes'),
            'rate_limit': rate_limit,
            'expires_days': expires_days or None
        }

        key = service.create_api_key(data)
        if key:
            flash(f'API Key created: {key.key_value}. Save this key - it will not be shown again!', 'success')
            return redirect(url_for('api_gateway.list_keys'))
        else:
            flash('Failed to create API key.', 'error')

    scopes = [
        {'id': 'read:resources', 'name': 'Read Resources', 'description': 'View infrastructure resources'},
        {'id': 'write:resources', 'name': 'Write Resources', 'description': 'Create/update resources'},
        {'id': 'delete:resources', 'name': 'Delete Resources', 'description': 'Delete resources'},
        {'id': 'read:analytics', 'name': 'Read Analytics', 'description': 'View analytics data'},
        {'id': 'read:incidents', 'name': 'Read Incidents', 'description': 'View incidents'},
        {'id': 'write:incidents', 'name': 'Write Incidents', 'description': 'Create/update incidents'},
        {'id': 'admin', 'name': 'Admin Access', 'description': 'Full administrative access'},
    ]
    return render_template('api_gateway/create_key.html', scopes=scopes)


@api_gateway_bp.route('/keys/<int:key_id>/revoke', methods=['POST'])
@login_required
def revoke_key(key_id):
    """Revoke an API key"""
    from services.api_gateway import APIGatewayService
    service = APIGatewayService()

    if service.revoke_api_key(key_id, current_user.id):
        flash('API key revoked.', 'success')
    else:
        flash('Failed to revoke API key.', 'error')

    return redirect(url_for('api_gateway.list_keys'))


@api_gateway_bp.route('/webhooks')
@login_required
def list_webhooks():
    """List webhooks"""
    from services.api_gateway import APIGatewayService
    service = APIGatewayService()
    webhooks = service.get_user_webhooks(current_user.id)
    return render_template('api_gateway/webhooks.html', webhooks=webhooks)


@api_gateway_bp.route('/webhooks/create', methods=['GET', 'POST'])
@login_required
def create_webhook():
    """Create new webhook"""
    if request.method == 'POST':
        from services.api_gateway import APIGatewayService
        service = APIGatewayService()

        data = {
            'user_id': current_user.id,
            'name': request.form.get('name'),
            'url': request.form.get('url'),
            'events': request.form.getlist('events'),
            'secret': request.form.get('secret'),
            'headers': {}
        }

        custom_headers = request.form.get('custom_headers')
        if custom_headers:
            import json
            try:
                data['headers'] = json.loads(custom_headers)
            except (ValueError, TypeError):
                pass

        webhook = service.create_webhook(data)
        if webhook:
            flash('Webhook created successfully!', 'success')
            return redirect(url_for('api_gateway.list_webhooks'))
        else:
            flash('Failed to create webhook.', 'error')

    events = [
        {'id': 'resource.created', 'name': 'Resource Created'},
        {'id': 'resource.updated', 'name': 'Resource Updated'},
        {'id': 'resource.deleted', 'name': 'Resource Deleted'},
        {'id': 'incident.created', 'name': 'Incident Created'},
        {'id': 'incident.resolved', 'name': 'Incident Resolved'},
        {'id': 'alert.triggered', 'name': 'Alert Triggered'},
        {'id': 'deployment.started', 'name': 'Deployment Started'},
        {'id': 'deployment.completed', 'name': 'Deployment Completed'},
        {'id': 'deployment.failed', 'name': 'Deployment Failed'},
        {'id': 'cost.threshold', 'name': 'Cost Threshold Exceeded'},
    ]
    return render_template('api_gateway/create_webhook.html', events=events)


@api_gateway_bp.route('/webhooks/<int:webhook_id>/toggle', methods=['POST'])
@login_required
def toggle_webhook(webhook_id):
    """Enable/disable webhook"""
    from services.api_gateway import APIGatewayService
    service = APIGatewayService()

    if service.toggle_webhook(webhook_id, current_user.id):
        flash('Webhook status updated.', 'success')
    else:
        flash('Failed to update webhook.', 'error')

    return redirect(url_for('api_gateway.list_webhooks'))


@api_gateway_bp.route('/webhooks/<int:webhook_id>/delete', methods=['POST'])
@login_required
def delete_webhook(webhook_id):
    """Delete webhook"""
    from services.api_gateway import APIGatewayService
    service = APIGatewayService()

    if service.delete_webhook(webhook_id, current_user.id):
        flash('Webhook deleted.', 'success')
    else:
        flash('Failed to delete webhook.', 'error')

    return redirect(url_for('api_gateway.list_webhooks'))


@api_gateway_bp.route('/webhooks/<int:webhook_id>/test', methods=['POST'])
@login_required
def test_webhook(webhook_id):
    """Test webhook delivery"""
    from services.api_gateway import APIGatewayService
    service = APIGatewayService()

    result = service.test_webhook(webhook_id, current_user.id)
    if result.get('success'):
        flash('Test webhook delivered successfully!', 'success')
    else:
        flash(f'Webhook test failed: {result.get("error")}', 'error')

    return redirect(url_for('api_gateway.list_webhooks'))


@api_gateway_bp.route('/usage')
@login_required
def usage_stats():
    """API usage statistics"""
    from services.api_gateway import APIGatewayService
    service = APIGatewayService()
    stats = service.get_api_usage_stats(current_user.id)
    return render_template('api_gateway/usage.html', stats=stats)


@api_gateway_bp.route('/docs')
@login_required
def api_docs():
    """API documentation"""
    return render_template('api_gateway/docs.html')


# External API endpoints (for SDK/external use)
@api_gateway_bp.route('/v1/resources', methods=['GET'])
@api_key_required
def api_list_resources():
    """External API: List resources"""
    from models import InfrastructureResource

    resources = InfrastructureResource.query.filter_by(
        user_id=request.api_key.user_id
    ).all()

    return jsonify({
        'resources': [{
            'id': r.id,
            'name': r.name,
            'type': r.resource_type,
            'provider': r.provider,
            'status': r.status,
            'region': r.region,
            'created_at': r.created_at.isoformat() if r.created_at else None
        } for r in resources]
    })


@api_gateway_bp.route('/v1/resources/<resource_id>', methods=['GET'])
@api_key_required
def api_get_resource(resource_id):
    """External API: Get resource details"""
    from models import InfrastructureResource

    resource = InfrastructureResource.query.filter_by(
        id=resource_id,
        user_id=request.api_key.user_id
    ).first()

    if not resource:
        return jsonify({'error': 'Resource not found'}), 404

    return jsonify({
        'resource': {
            'id': resource.id,
            'name': resource.name,
            'type': resource.resource_type,
            'provider': resource.provider,
            'status': resource.status,
            'region': resource.region,
            'resource_id': resource.resource_id,
            'metadata': resource.metadata,
            'created_at': resource.created_at.isoformat() if resource.created_at else None,
            'last_synced': resource.last_synced.isoformat() if resource.last_synced else None
        }
    })


@api_gateway_bp.route('/v1/analytics/costs', methods=['GET'])
@api_key_required
def api_get_costs():
    """External API: Get cost data"""
    from services.analytics_service import AnalyticsService
    from datetime import datetime, timedelta

    period = request.args.get('period', '30d')
    try:
        days = max(1, min(int(period.rstrip('dh')), 365))
    except (ValueError, TypeError):
        days = 30

    service = AnalyticsService(request.api_key.user_id)
    start_date = datetime.utcnow() - timedelta(days=days)
    end_date = datetime.utcnow()

    data = service.get_cost_analytics(start_date, end_date)
    return jsonify(data)


@api_gateway_bp.route('/v1/incidents', methods=['GET'])
@api_key_required
def api_list_incidents():
    """External API: List incidents"""
    from models import Incident

    status = request.args.get('status')
    query = Incident.query.filter_by(user_id=request.api_key.user_id)

    if status:
        query = query.filter_by(status=status)

    incidents = query.order_by(Incident.created_at.desc()).limit(100).all()

    return jsonify({
        'incidents': [{
            'id': i.id,
            'title': i.title,
            'severity': i.severity,
            'status': i.status,
            'created_at': i.created_at.isoformat() if i.created_at else None,
            'resolved_at': i.resolved_at.isoformat() if i.resolved_at else None
        } for i in incidents]
    })


@api_gateway_bp.route('/v1/incidents', methods=['POST'])
@api_key_required
def api_create_incident():
    """External API: Create incident"""
    from models import db, Incident
    from datetime import datetime

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400

    incident = Incident(
        user_id=request.api_key.user_id,
        title=data.get('title'),
        description=data.get('description'),
        severity=data.get('severity', 'medium'),
        status='open',
        created_at=datetime.utcnow()
    )

    db.session.add(incident)
    db.session.commit()

    from services.api_gateway import APIGatewayService
    gateway = APIGatewayService()
    gateway.trigger_webhooks(request.api_key.user_id, 'incident.created', {
        'incident_id': incident.id,
        'title': incident.title,
        'severity': incident.severity
    })

    return jsonify({
        'incident': {
            'id': incident.id,
            'title': incident.title,
            'status': incident.status
        }
    }), 201


@api_gateway_bp.route('/v1/health', methods=['GET'])
def api_health():
    """External API: Health check"""
    return jsonify({
        'status': 'healthy',
        'version': '1.0.0',
        'timestamp': time.time()
    })


# Dashboard API endpoints
@api_gateway_bp.route('/api/stats')
@login_required
def dashboard_stats():
    """Get API gateway stats for dashboard"""
    from services.api_gateway import APIGatewayService
    service = APIGatewayService()

    stats = service.get_api_usage_stats(current_user.id)
    keys = service.get_user_api_keys(current_user.id)
    webhooks = service.get_user_webhooks(current_user.id)

    return jsonify({
        'total_keys': len(keys),
        'active_keys': len([k for k in keys if k.is_active]),
        'total_webhooks': len(webhooks),
        'active_webhooks': len([w for w in webhooks if w.is_active]),
        'requests_today': stats.get('requests_today', 0),
        'requests_month': stats.get('requests_month', 0),
        'rate_limit_hits': stats.get('rate_limit_hits', 0)
    })
