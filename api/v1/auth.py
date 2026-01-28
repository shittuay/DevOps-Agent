"""
Authentication API Endpoints

Provides token-based authentication for the API.
"""

from flask import jsonify, request, g
from datetime import datetime
from api.v1 import api_v1_bp
from services.api_key_service import require_api_key


@api_v1_bp.route('/auth/validate', methods=['GET'])
@require_api_key()
def validate_token():
    """
    Validate an API key and return user info.

    Requires: API key authentication
    """
    return jsonify({
        'valid': True,
        'user': g.api_user.to_dict() if g.api_user else None,
        'key': {
            'name': g.api_key.name,
            'scopes': g.api_key.scopes,
            'expires_at': g.api_key.expires_at.isoformat() if g.api_key.expires_at else None
        }
    })


@api_v1_bp.route('/auth/me', methods=['GET'])
@require_api_key(scope='read')
def get_current_user():
    """
    Get current authenticated user information.

    Requires: API key with 'read' scope
    """
    user = g.api_user

    # Get subscription info
    subscription = None
    if user.subscription:
        subscription = {
            'tier': user.subscription.tier.name if user.subscription.tier else None,
            'credits_remaining': user.subscription.credits_remaining,
            'credits_used_this_month': user.subscription.credits_used_this_month
        }

    return jsonify({
        'user': user.to_dict(),
        'subscription': subscription,
        'two_factor_enabled': user.two_factor_enabled
    })


@api_v1_bp.route('/auth/usage', methods=['GET'])
@require_api_key(scope='read')
def get_usage_stats():
    """
    Get API usage statistics for the current key.

    Requires: API key with 'read' scope
    """
    key = g.api_key

    return jsonify({
        'api_key': {
            'name': key.name,
            'total_requests': key.total_requests,
            'requests_today': key.requests_today,
            'rate_limit': key.rate_limit,
            'rate_limit_remaining': max(0, key.rate_limit - key.requests_today),
            'last_used_at': key.last_used_at.isoformat() if key.last_used_at else None
        }
    })
