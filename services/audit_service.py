"""
Audit Logging Service

Provides comprehensive audit logging for all user and system actions.
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from functools import wraps

from flask import request, g

logger = logging.getLogger(__name__)


class AuditService:
    """
    Service for managing audit logs.

    Features:
    - Automatic request context capture
    - Action categorization
    - Searchable audit trail
    - Retention management
    """

    # Action categories
    CATEGORIES = {
        'auth': ['login', 'logout', 'login_failed', 'password_change', '2fa_enable', '2fa_disable'],
        'resource': ['create', 'update', 'delete', 'start', 'stop', 'sync'],
        'billing': ['subscription_create', 'subscription_cancel', 'credit_purchase', 'payment'],
        'security': ['api_key_create', 'api_key_revoke', 'credential_update', 'permission_change'],
        'settings': ['profile_update', 'preference_update', 'notification_update'],
        'admin': ['user_create', 'user_delete', 'role_change', 'system_config']
    }

    def __init__(self, app=None):
        if app:
            self.init_app(app)

    def init_app(self, app):
        """Initialize with Flask app."""
        app.extensions = getattr(app, 'extensions', {})
        app.extensions['audit'] = self

    def log(self, action: str, category: str, user_id: int = None,
            resource_type: str = None, resource_id: str = None,
            description: str = None, old_value: Any = None, new_value: Any = None,
            status: str = 'success', error_message: str = None,
            metadata: Dict[str, Any] = None) -> Optional[object]:
        """
        Create an audit log entry.

        Args:
            action: The action performed (e.g., 'login', 'create_resource')
            category: Action category (auth, resource, billing, security, settings, admin)
            user_id: ID of the user performing the action (None for system actions)
            resource_type: Type of affected resource
            resource_id: ID of affected resource
            description: Human-readable description
            old_value: Previous state (for updates)
            new_value: New state (for creates/updates)
            status: Result status (success, failure, error)
            error_message: Error message if failed
            metadata: Additional context

        Returns:
            AuditLog instance
        """
        from models import AuditLog, db

        # Capture request context if available
        ip_address = None
        user_agent = None
        request_method = None
        request_path = None
        api_key_id = None

        try:
            if request:
                ip_address = request.remote_addr
                user_agent = request.headers.get('User-Agent', '')[:500]
                request_method = request.method
                request_path = request.path[:500]

            if hasattr(g, 'api_key') and g.api_key:
                api_key_id = g.api_key.id
        except RuntimeError:
            # Outside request context
            pass

        log_entry = AuditLog(
            user_id=user_id,
            action=action,
            action_category=category,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            ip_address=ip_address,
            user_agent=user_agent,
            request_method=request_method,
            request_path=request_path,
            api_key_id=api_key_id,
            description=description,
            old_value=old_value,
            new_value=new_value,
            metadata=metadata,
            status=status,
            error_message=error_message
        )

        db.session.add(log_entry)
        db.session.commit()

        logger.debug(f"Audit log: {action} by user {user_id} - {status}")
        return log_entry

    def log_auth(self, action: str, user_id: int = None, **kwargs):
        """Log authentication-related actions."""
        return self.log(action, 'auth', user_id=user_id, **kwargs)

    def log_resource(self, action: str, user_id: int, resource_type: str,
                     resource_id: str = None, **kwargs):
        """Log resource-related actions."""
        return self.log(action, 'resource', user_id=user_id,
                       resource_type=resource_type, resource_id=resource_id, **kwargs)

    def log_billing(self, action: str, user_id: int, **kwargs):
        """Log billing-related actions."""
        return self.log(action, 'billing', user_id=user_id, **kwargs)

    def log_security(self, action: str, user_id: int, **kwargs):
        """Log security-related actions."""
        return self.log(action, 'security', user_id=user_id, **kwargs)

    def log_settings(self, action: str, user_id: int, **kwargs):
        """Log settings-related actions."""
        return self.log(action, 'settings', user_id=user_id, **kwargs)

    def log_admin(self, action: str, user_id: int, **kwargs):
        """Log admin-related actions."""
        return self.log(action, 'admin', user_id=user_id, **kwargs)

    def get_user_logs(self, user_id: int, limit: int = 100, offset: int = 0,
                      category: str = None, action: str = None,
                      start_date: datetime = None, end_date: datetime = None) -> List[object]:
        """
        Get audit logs for a specific user.

        Args:
            user_id: User ID
            limit: Number of logs to return
            offset: Offset for pagination
            category: Filter by category
            action: Filter by action
            start_date: Filter by start date
            end_date: Filter by end date

        Returns:
            List of AuditLog instances
        """
        from models import AuditLog

        query = AuditLog.query.filter_by(user_id=user_id)

        if category:
            query = query.filter_by(action_category=category)

        if action:
            query = query.filter_by(action=action)

        if start_date:
            query = query.filter(AuditLog.created_at >= start_date)

        if end_date:
            query = query.filter(AuditLog.created_at <= end_date)

        return query.order_by(AuditLog.created_at.desc())\
            .limit(limit)\
            .offset(offset)\
            .all()

    def get_all_logs(self, limit: int = 100, offset: int = 0, **filters) -> tuple:
        """
        Get all audit logs (admin only).

        Returns:
            Tuple of (logs list, total count)
        """
        from models import AuditLog

        query = AuditLog.query

        if filters.get('user_id'):
            query = query.filter_by(user_id=filters['user_id'])

        if filters.get('category'):
            query = query.filter_by(action_category=filters['category'])

        if filters.get('action'):
            query = query.filter_by(action=filters['action'])

        if filters.get('status'):
            query = query.filter_by(status=filters['status'])

        if filters.get('start_date'):
            query = query.filter(AuditLog.created_at >= filters['start_date'])

        if filters.get('end_date'):
            query = query.filter(AuditLog.created_at <= filters['end_date'])

        if filters.get('ip_address'):
            query = query.filter_by(ip_address=filters['ip_address'])

        total = query.count()
        logs = query.order_by(AuditLog.created_at.desc())\
            .limit(limit)\
            .offset(offset)\
            .all()

        return logs, total

    def get_stats(self, days: int = 30) -> Dict[str, Any]:
        """
        Get audit log statistics.

        Args:
            days: Number of days to include

        Returns:
            Statistics dictionary
        """
        from models import AuditLog
        from sqlalchemy import func

        start_date = datetime.utcnow() - timedelta(days=days)

        # Get counts by category
        category_counts = AuditLog.query.filter(
            AuditLog.created_at >= start_date
        ).with_entities(
            AuditLog.action_category,
            func.count(AuditLog.id)
        ).group_by(AuditLog.action_category).all()

        # Get counts by status
        status_counts = AuditLog.query.filter(
            AuditLog.created_at >= start_date
        ).with_entities(
            AuditLog.status,
            func.count(AuditLog.id)
        ).group_by(AuditLog.status).all()

        # Get daily activity
        daily_counts = AuditLog.query.filter(
            AuditLog.created_at >= start_date
        ).with_entities(
            func.date(AuditLog.created_at),
            func.count(AuditLog.id)
        ).group_by(func.date(AuditLog.created_at)).all()

        return {
            'period_days': days,
            'total_events': sum(count for _, count in category_counts),
            'by_category': {cat: count for cat, count in category_counts},
            'by_status': {status: count for status, count in status_counts},
            'daily_activity': [
                {'date': date.isoformat() if date else None, 'count': count}
                for date, count in daily_counts
            ]
        }

    def cleanup_old_logs(self, days_to_keep: int = 365) -> int:
        """
        Delete audit logs older than specified days.

        Args:
            days_to_keep: Number of days to retain logs

        Returns:
            Number of deleted logs
        """
        from models import AuditLog, db

        cutoff = datetime.utcnow() - timedelta(days=days_to_keep)

        deleted = AuditLog.query.filter(
            AuditLog.created_at < cutoff
        ).delete()

        db.session.commit()
        logger.info(f"Deleted {deleted} audit logs older than {days_to_keep} days")

        return deleted


# Global service instance
audit_service = AuditService()


def init_audit_service(app):
    """Initialize audit service with Flask app."""
    audit_service.init_app(app)
    return audit_service


# ==========================================
# Decorator for automatic audit logging
# ==========================================

def audit_action(action: str, category: str, resource_type: str = None,
                 get_resource_id=None, get_description=None):
    """
    Decorator to automatically log actions.

    Usage:
        @app.route('/api/resources', methods=['POST'])
        @audit_action('create', 'resource', resource_type='ec2_instance')
        def create_resource():
            ...

    Args:
        action: Action name
        category: Action category
        resource_type: Type of resource (optional)
        get_resource_id: Function to extract resource ID from response
        get_description: Function to generate description
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            from flask_login import current_user

            user_id = None
            if hasattr(g, 'api_user') and g.api_user:
                user_id = g.api_user.id
            elif current_user and current_user.is_authenticated:
                user_id = current_user.id

            try:
                result = f(*args, **kwargs)

                # Extract resource ID if function provided
                resource_id = None
                if get_resource_id and result:
                    try:
                        resource_id = get_resource_id(result)
                    except Exception:
                        pass

                # Generate description if function provided
                description = None
                if get_description:
                    try:
                        description = get_description(result)
                    except Exception:
                        pass

                # Log successful action
                audit_service.log(
                    action=action,
                    category=category,
                    user_id=user_id,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    description=description,
                    status='success'
                )

                return result

            except Exception as e:
                # Log failed action
                audit_service.log(
                    action=action,
                    category=category,
                    user_id=user_id,
                    resource_type=resource_type,
                    status='error',
                    error_message=str(e)
                )
                raise

        return decorated_function
    return decorator
