"""
Health Check API Endpoints

Provides system health and status information.
"""

from flask import jsonify
from datetime import datetime
from api.v1 import api_v1_bp


@api_v1_bp.route('/health', methods=['GET'])
def health_check():
    """
    Basic health check endpoint.

    Returns 200 if the service is running.
    No authentication required.
    """
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'service': 'devops-agent',
        'version': '1.0.0'
    })


@api_v1_bp.route('/health/detailed', methods=['GET'])
def detailed_health_check():
    """
    Detailed health check with component status.

    No authentication required.
    """
    from models import db
    from services.cache_service import cache

    health = {
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'components': {}
    }

    # Check database
    try:
        db.session.execute(db.text('SELECT 1'))
        health['components']['database'] = {'status': 'healthy'}
    except Exception as e:
        health['components']['database'] = {'status': 'unhealthy', 'error': str(e)}
        health['status'] = 'unhealthy'

    # Check cache
    try:
        cache_stats = cache.get_stats()
        health['components']['cache'] = {
            'status': 'healthy' if cache_stats['enabled'] else 'degraded',
            'backend': cache_stats['backend']
        }
    except Exception as e:
        health['components']['cache'] = {'status': 'unhealthy', 'error': str(e)}

    return jsonify(health), 200 if health['status'] == 'healthy' else 503


@api_v1_bp.route('/status', methods=['GET'])
def service_status():
    """
    Service status and metrics.

    No authentication required.
    """
    from models import User, Conversation

    return jsonify({
        'status': 'operational',
        'timestamp': datetime.utcnow().isoformat(),
        'metrics': {
            'total_users': User.query.count(),
            'total_conversations': Conversation.query.count()
        }
    })
