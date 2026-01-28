"""
Cloud Resources API Endpoints

Provides cloud infrastructure resource management endpoints.
"""

from flask import jsonify, request, g
from api.v1 import api_v1_bp
from services.api_key_service import require_api_key


@api_v1_bp.route('/resources', methods=['GET'])
@require_api_key(scope='read')
def list_resources():
    """
    List user's cloud resources.

    Requires: API key with 'read' scope

    Query Parameters:
        provider (string): Filter by cloud provider (aws, gcp, azure)
        type (string): Filter by resource type
        status (string): Filter by status
        limit (int): Number of resources to return (default: 50, max: 200)
        offset (int): Offset for pagination (default: 0)
    """
    from models import InfrastructureResource

    user_id = g.api_user.id
    limit = min(request.args.get('limit', 50, type=int), 200)
    offset = request.args.get('offset', 0, type=int)

    query = InfrastructureResource.query.filter_by(user_id=user_id)

    # Apply filters
    if request.args.get('provider'):
        query = query.filter_by(cloud_provider=request.args['provider'])

    if request.args.get('type'):
        query = query.filter_by(resource_type=request.args['type'])

    if request.args.get('status'):
        query = query.filter_by(status=request.args['status'])

    total = query.count()
    resources = query.order_by(InfrastructureResource.created_at.desc())\
        .limit(limit)\
        .offset(offset)\
        .all()

    return jsonify({
        'resources': [r.to_dict() for r in resources],
        'pagination': {
            'total': total,
            'limit': limit,
            'offset': offset,
            'has_more': offset + limit < total
        }
    })


@api_v1_bp.route('/resources/<int:resource_id>', methods=['GET'])
@require_api_key(scope='read')
def get_resource(resource_id):
    """
    Get a specific cloud resource.

    Requires: API key with 'read' scope
    """
    from models import InfrastructureResource

    resource = InfrastructureResource.query.filter_by(
        id=resource_id,
        user_id=g.api_user.id
    ).first()

    if not resource:
        return jsonify({
            'error': 'Not found',
            'message': 'Resource not found'
        }), 404

    return jsonify(resource.to_dict())


@api_v1_bp.route('/resources/sync', methods=['POST'])
@require_api_key(scope='write')
def sync_resources():
    """
    Trigger a sync of cloud resources.

    Requires: API key with 'write' scope

    Body:
        provider (string, optional): Sync specific provider only
    """
    from tasks.cloud_tasks import sync_cloud_resources

    user_id = g.api_user.id
    data = request.get_json() or {}
    provider = data.get('provider')

    if provider:
        # Sync specific provider
        task = sync_cloud_resources.delay(user_id, provider)
    else:
        # Sync all providers
        for p in ['aws', 'gcp', 'azure']:
            sync_cloud_resources.delay(user_id, p)

    return jsonify({
        'message': 'Sync initiated',
        'provider': provider or 'all'
    }), 202


@api_v1_bp.route('/resources/stats', methods=['GET'])
@require_api_key(scope='read')
def get_resource_stats():
    """
    Get resource statistics summary.

    Requires: API key with 'read' scope
    """
    from models import InfrastructureResource
    from sqlalchemy import func

    user_id = g.api_user.id

    # Get counts by provider
    provider_counts = InfrastructureResource.query.filter_by(user_id=user_id)\
        .with_entities(
            InfrastructureResource.cloud_provider,
            func.count(InfrastructureResource.id)
        )\
        .group_by(InfrastructureResource.cloud_provider)\
        .all()

    # Get counts by status
    status_counts = InfrastructureResource.query.filter_by(user_id=user_id)\
        .with_entities(
            InfrastructureResource.status,
            func.count(InfrastructureResource.id)
        )\
        .group_by(InfrastructureResource.status)\
        .all()

    # Get total monthly cost
    total_cost = InfrastructureResource.query.filter_by(user_id=user_id)\
        .with_entities(func.sum(InfrastructureResource.monthly_cost))\
        .scalar() or 0

    return jsonify({
        'total_resources': sum(count for _, count in provider_counts),
        'by_provider': {provider: count for provider, count in provider_counts},
        'by_status': {status: count for status, count in status_counts},
        'estimated_monthly_cost': round(total_cost, 2)
    })


@api_v1_bp.route('/resources/alerts', methods=['GET'])
@require_api_key(scope='read')
def list_resource_alerts():
    """
    List active alerts for user's resources.

    Requires: API key with 'read' scope

    Query Parameters:
        severity (string): Filter by severity (critical, warning, info)
        status (string): Filter by status (active, acknowledged, resolved)
        limit (int): Number of alerts to return (default: 50)
    """
    from models import Alert

    user_id = g.api_user.id
    limit = min(request.args.get('limit', 50, type=int), 200)

    query = Alert.query.filter_by(user_id=user_id)

    if request.args.get('severity'):
        query = query.filter_by(severity=request.args['severity'])

    if request.args.get('status'):
        query = query.filter_by(status=request.args['status'])
    else:
        # Default to active alerts
        query = query.filter_by(status='active')

    alerts = query.order_by(Alert.triggered_at.desc())\
        .limit(limit)\
        .all()

    return jsonify({
        'alerts': [a.to_dict() for a in alerts]
    })


@api_v1_bp.route('/resources/security', methods=['GET'])
@require_api_key(scope='read')
def list_security_findings():
    """
    List security findings for user's resources.

    Requires: API key with 'read' scope

    Query Parameters:
        severity (string): Filter by severity
        status (string): Filter by status (open, in_progress, resolved)
        limit (int): Number of findings to return (default: 50)
    """
    from models import SecurityFinding

    user_id = g.api_user.id
    limit = min(request.args.get('limit', 50, type=int), 200)

    query = SecurityFinding.query.filter_by(user_id=user_id)

    if request.args.get('severity'):
        query = query.filter_by(severity=request.args['severity'])

    if request.args.get('status'):
        query = query.filter_by(status=request.args['status'])
    else:
        query = query.filter_by(status='open')

    findings = query.order_by(SecurityFinding.first_detected.desc())\
        .limit(limit)\
        .all()

    return jsonify({
        'findings': [f.to_dict() for f in findings]
    })
