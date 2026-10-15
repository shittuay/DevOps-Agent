"""
Tier Enforcement Service

Provides decorators and helpers to gate features by subscription tier.
"""
from functools import wraps
from flask import jsonify
from flask_login import current_user


def get_user_tier(user_id):
    """Get user's current subscription tier. Returns SubscriptionTier or None."""
    from models import UserSubscription
    sub = UserSubscription.query.filter_by(user_id=user_id).first()
    if sub and sub.tier:
        return sub.tier
    return None


def _get_free_tier():
    """Get the free tier as fallback."""
    from models import SubscriptionTier
    return SubscriptionTier.query.filter_by(name='free').first()


def check_resource_limit(user_id, limit_type):
    """
    Check if user is within their tier's resource limits.

    Args:
        user_id: User ID
        limit_type: 'cloud_accounts', 'resources', 'team_members'

    Returns:
        (allowed: bool, current: int, limit: int)
    """
    from models import UserCloudCredential, InfrastructureResource, User

    tier = get_user_tier(user_id) or _get_free_tier()
    if not tier:
        return False, 0, 0

    if limit_type == 'cloud_accounts':
        current = UserCloudCredential.query.filter_by(
            user_id=user_id, is_active=True
        ).count()
        limit = tier.max_cloud_accounts or 1
    elif limit_type == 'resources':
        current = InfrastructureResource.query.filter_by(
            user_id=user_id
        ).count()
        limit = tier.max_resources or 50
    elif limit_type == 'team_members':
        current = User.query.filter(User.id != user_id).count()
        limit = tier.max_team_members or 1
    else:
        return True, 0, 999

    return current < limit, current, limit


def check_feature(user_id, feature_name):
    """
    Check if user's tier includes a boolean feature.

    Args:
        user_id: User ID
        feature_name: 'has_pdf_export', 'has_auto_remediation', 'has_sso', 'has_audit_export'

    Returns:
        bool
    """
    tier = get_user_tier(user_id) or _get_free_tier()
    if not tier:
        return False
    return getattr(tier, feature_name, False)


def require_feature(feature_name):
    """Decorator that checks if user's tier has a specific feature."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not check_feature(current_user.id, feature_name):
                tier = get_user_tier(current_user.id)
                tier_name = tier.display_name if tier else 'Free'
                return jsonify({
                    'error': 'upgrade_required',
                    'message': f'This feature is not available on the {tier_name} plan. Please upgrade to access it.',
                    'current_tier': tier_name,
                    'upgrade_url': '/billing'
                }), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_resource_limit(limit_type):
    """Decorator that checks resource limits before allowing creation."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            allowed, current, limit = check_resource_limit(current_user.id, limit_type)
            if not allowed:
                tier = get_user_tier(current_user.id)
                tier_name = tier.display_name if tier else 'Free'
                labels = {
                    'cloud_accounts': 'cloud accounts',
                    'resources': 'resources',
                    'team_members': 'team members',
                }
                return jsonify({
                    'error': 'limit_reached',
                    'message': f'You have reached the maximum of {limit} {labels.get(limit_type, limit_type)} on the {tier_name} plan. Please upgrade for more.',
                    'current': current,
                    'limit': limit,
                    'current_tier': tier_name,
                    'upgrade_url': '/billing'
                }), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator
