"""
User API Endpoints

Provides user management endpoints.
"""

from flask import jsonify, request, g
from api.v1 import api_v1_bp
from services.api_key_service import require_api_key
from src.utils.timeutils import utcnow


@api_v1_bp.route('/users/me', methods=['GET'])
@require_api_key(scope='read')
def get_user_profile():
    """
    Get current user's profile.

    Requires: API key with 'read' scope
    """
    user = g.api_user
    return jsonify({
        'user': user.to_dict()
    })


@api_v1_bp.route('/users/me', methods=['PATCH'])
@require_api_key(scope='write')
def update_user_profile():
    """
    Update current user's profile.

    Requires: API key with 'write' scope

    Body:
        full_name (string, optional): User's full name
        bio (string, optional): User's bio
        avatar_color (string, optional): Avatar color (hex)
        language (string, optional): Preferred language
    """
    from models import db

    user = g.api_user
    data = request.get_json() or {}

    # Allowed fields to update
    allowed_fields = ['full_name', 'bio', 'avatar_color', 'language']

    for field in allowed_fields:
        if field in data:
            setattr(user, field, data[field])

    db.session.commit()

    return jsonify({
        'message': 'Profile updated',
        'user': user.to_dict()
    })


@api_v1_bp.route('/users/me/preferences', methods=['GET'])
@require_api_key(scope='read')
def get_user_preferences():
    """
    Get user preferences.

    Requires: API key with 'read' scope
    """
    from models import UserPreferences

    prefs = UserPreferences.query.filter_by(user_id=g.api_user.id).first()

    if not prefs:
        return jsonify({'preferences': None})

    return jsonify({
        'preferences': prefs.to_dict()
    })


@api_v1_bp.route('/users/me/preferences', methods=['PATCH'])
@require_api_key(scope='write')
def update_user_preferences():
    """
    Update user preferences.

    Requires: API key with 'write' scope
    """
    from models import db, UserPreferences

    user_id = g.api_user.id
    data = request.get_json() or {}

    prefs = UserPreferences.query.filter_by(user_id=user_id).first()

    if not prefs:
        prefs = UserPreferences(user_id=user_id)
        db.session.add(prefs)

    # Update allowed preference fields
    allowed_fields = [
        'aws_default_region', 'aws_default_instance_type',
        'azure_default_region', 'azure_default_vm_size',
        'gcp_default_region', 'gcp_default_zone',
        'k8s_default_namespace', 'k8s_default_replicas',
        'preferred_cloud_provider', 'enable_cost_warnings',
        'enable_suggestions', 'verbose_mode'
    ]

    for field in allowed_fields:
        if field in data:
            setattr(prefs, field, data[field])

    db.session.commit()

    return jsonify({
        'message': 'Preferences updated',
        'preferences': prefs.to_dict()
    })


@api_v1_bp.route('/users/me/subscription', methods=['GET'])
@require_api_key(scope='read')
def get_user_subscription():
    """
    Get user's subscription details.

    Requires: API key with 'read' scope
    """
    user = g.api_user
    subscription = user.subscription

    if not subscription:
        return jsonify({
            'subscription': None,
            'message': 'No active subscription'
        })

    return jsonify({
        'subscription': subscription.to_dict()
    })


@api_v1_bp.route('/users/me/usage', methods=['GET'])
@require_api_key(scope='read')
def get_user_usage():
    """
    Get user's usage statistics.

    Requires: API key with 'read' scope
    """
    from models import UsageLog, Conversation
    from datetime import datetime, timedelta
    from sqlalchemy import func

    user_id = g.api_user.id

    # Get usage for last 30 days
    thirty_days_ago = utcnow() - timedelta(days=30)

    usage_stats = UsageLog.query.filter(
        UsageLog.user_id == user_id,
        UsageLog.created_at >= thirty_days_ago
    ).with_entities(
        func.count(UsageLog.id).label('total_actions'),
        func.sum(UsageLog.credits_used).label('credits_used')
    ).first()

    conversation_count = Conversation.query.filter(
        Conversation.user_id == user_id,
        Conversation.created_at >= thirty_days_ago
    ).count()

    return jsonify({
        'period': '30_days',
        'total_actions': usage_stats.total_actions or 0,
        'credits_used': usage_stats.credits_used or 0,
        'conversations_created': conversation_count
    })
