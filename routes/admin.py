"""
Admin routes for user management and system administration.
"""

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from models import db, User, UsageLog, Conversation, ChatMessage
from services.rbac import (
    admin_required, approver_required, require_permission, require_role,
    Permission, Role, get_all_roles, get_assignable_roles,
    get_user_role, user_can_manage_user, RBACContext
)
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route('/')
@login_required
@admin_required
def admin_dashboard():
    """Admin dashboard with system overview."""
    # Get user statistics
    total_users = User.query.count()
    active_users = User.query.filter(
        User.last_login >= datetime.utcnow() - timedelta(days=30)
    ).count()

    # Users by role
    users_by_role = {
        'admin': User.query.filter_by(role='admin').count(),
        'approver': User.query.filter_by(role='approver').count(),
        'user': User.query.filter_by(role='user').count(),
        'viewer': User.query.filter_by(role='viewer').count()
    }

    # Recent signups
    recent_users = User.query.order_by(User.created_at.desc()).limit(10).all()

    # Get conversation count
    total_conversations = Conversation.query.count()
    total_messages = ChatMessage.query.count()

    return render_template('admin/dashboard.html',
        total_users=total_users,
        active_users=active_users,
        users_by_role=users_by_role,
        recent_users=recent_users,
        total_conversations=total_conversations,
        total_messages=total_messages,
        roles=get_all_roles()
    )


@admin_bp.route('/users')
@login_required
@admin_required
def list_users():
    """List all users with filtering and pagination."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    role_filter = request.args.get('role', None)
    search = request.args.get('search', None)

    query = User.query

    if role_filter:
        query = query.filter_by(role=role_filter)

    if search:
        query = query.filter(
            db.or_(
                User.email.ilike(f'%{search}%'),
                User.username.ilike(f'%{search}%'),
                User.full_name.ilike(f'%{search}%')
            )
        )

    users = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template('admin/users.html',
        users=users,
        roles=get_all_roles(),
        current_role_filter=role_filter,
        search=search
    )


@admin_bp.route('/users/<int:user_id>')
@login_required
@admin_required
def view_user(user_id):
    """View user details."""
    user = User.query.get_or_404(user_id)

    # Get user's recent activity
    recent_conversations = Conversation.query.filter_by(user_id=user_id)\
        .order_by(Conversation.updated_at.desc()).limit(10).all()

    # Get message count
    message_count = ChatMessage.query.filter_by(user_id=user_id).count()

    return render_template('admin/user_detail.html',
        user=user,
        recent_conversations=recent_conversations,
        message_count=message_count,
        assignable_roles=get_assignable_roles(current_user),
        can_manage=user_can_manage_user(current_user, user)
    )


@admin_bp.route('/users/<int:user_id>/role', methods=['POST'])
@login_required
@admin_required
def update_user_role(user_id):
    """Update a user's role."""
    user = User.query.get_or_404(user_id)

    if not user_can_manage_user(current_user, user):
        return jsonify({
            'success': False,
            'error': 'You cannot modify this user\'s role'
        }), 403

    new_role = request.json.get('role')
    valid_roles = [r['name'] for r in get_assignable_roles(current_user)]

    if new_role not in valid_roles:
        return jsonify({
            'success': False,
            'error': f'Invalid role. You can assign: {", ".join(valid_roles)}'
        }), 400

    old_role = user.role
    user.role = new_role
    db.session.commit()

    logger.info(
        f"Role change: User {user.id} ({user.email}) role changed from "
        f"'{old_role}' to '{new_role}' by admin {current_user.id} ({current_user.email})"
    )

    return jsonify({
        'success': True,
        'message': f'Role updated to {new_role}',
        'old_role': old_role,
        'new_role': new_role
    })


@admin_bp.route('/users/<int:user_id>/lock', methods=['POST'])
@login_required
@admin_required
def lock_user(user_id):
    """Lock a user account."""
    user = User.query.get_or_404(user_id)

    if not user_can_manage_user(current_user, user):
        return jsonify({
            'success': False,
            'error': 'You cannot lock this user'
        }), 403

    duration_hours = request.json.get('duration', 24)
    user.locked_until = datetime.utcnow() + timedelta(hours=duration_hours)
    db.session.commit()

    logger.warning(
        f"Account locked: User {user.id} ({user.email}) locked for {duration_hours} hours "
        f"by admin {current_user.id} ({current_user.email})"
    )

    return jsonify({
        'success': True,
        'message': f'User locked for {duration_hours} hours',
        'locked_until': user.locked_until.isoformat()
    })


@admin_bp.route('/users/<int:user_id>/unlock', methods=['POST'])
@login_required
@admin_required
def unlock_user(user_id):
    """Unlock a user account."""
    user = User.query.get_or_404(user_id)

    if not user_can_manage_user(current_user, user):
        return jsonify({
            'success': False,
            'error': 'You cannot unlock this user'
        }), 403

    user.locked_until = None
    user.failed_login_attempts = 0
    db.session.commit()

    logger.info(
        f"Account unlocked: User {user.id} ({user.email}) unlocked "
        f"by admin {current_user.id} ({current_user.email})"
    )

    return jsonify({
        'success': True,
        'message': 'User account unlocked'
    })


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    """Delete a user account."""
    user = User.query.get_or_404(user_id)

    if not user_can_manage_user(current_user, user):
        return jsonify({
            'success': False,
            'error': 'You cannot delete this user'
        }), 403

    if user.id == current_user.id:
        return jsonify({
            'success': False,
            'error': 'You cannot delete your own account'
        }), 400

    email = user.email
    user_id_deleted = user.id

    # Delete user and cascade to related records
    db.session.delete(user)
    db.session.commit()

    logger.warning(
        f"User deleted: User {user_id_deleted} ({email}) deleted "
        f"by admin {current_user.id} ({current_user.email})"
    )

    return jsonify({
        'success': True,
        'message': f'User {email} deleted'
    })


@admin_bp.route('/audit-log')
@login_required
@require_permission(Permission.VIEW_AUDIT_LOGS)
def audit_log():
    """View system audit log."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # Get usage logs as audit trail
    logs = UsageLog.query.order_by(UsageLog.timestamp.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template('admin/audit_log.html', logs=logs)


@admin_bp.route('/settings')
@login_required
@admin_required
def system_settings():
    """System-wide settings."""
    return render_template('admin/settings.html')


# ==================== API ENDPOINTS ====================


@admin_bp.route('/api/users')
@login_required
@admin_required
def api_list_users():
    """API endpoint to list users."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    per_page = min(per_page, 200)
    query = User.query.order_by(User.created_at.desc())
    total = query.count()
    users = query.offset((page - 1) * per_page).limit(per_page).all()

    return jsonify({
        'success': True,
        'pagination': {'page': page, 'per_page': per_page, 'total': total},
        'users': [{
            'id': u.id,
            'email': u.email,
            'username': u.username,
            'full_name': u.full_name,
            'role': u.role,
            'created_at': u.created_at.isoformat() if u.created_at else None,
            'last_login': u.last_login.isoformat() if u.last_login else None,
            'is_locked': u.is_locked() if hasattr(u, 'is_locked') else False
        } for u in users]
    })


@admin_bp.route('/api/stats')
@login_required
@admin_required
def api_stats():
    """API endpoint for admin statistics."""
    total_users = User.query.count()
    active_today = User.query.filter(
        User.last_login >= datetime.utcnow() - timedelta(days=1)
    ).count()
    active_week = User.query.filter(
        User.last_login >= datetime.utcnow() - timedelta(days=7)
    ).count()

    return jsonify({
        'success': True,
        'stats': {
            'total_users': total_users,
            'active_today': active_today,
            'active_week': active_week,
            'users_by_role': {
                'admin': User.query.filter_by(role='admin').count(),
                'approver': User.query.filter_by(role='approver').count(),
                'user': User.query.filter_by(role='user').count(),
                'viewer': User.query.filter_by(role='viewer').count()
            }
        }
    })


@admin_bp.route('/api/roles')
@login_required
@admin_required
def api_roles():
    """API endpoint to get available roles."""
    return jsonify({
        'success': True,
        'roles': get_all_roles(),
        'assignable_roles': get_assignable_roles(current_user)
    })


@admin_bp.route('/funnel')
@login_required
@admin_required
def funnel_dashboard():
    """Signup-to-paid funnel: distinct users per milestone, and where they stop."""
    from services.funnel_analytics import get_funnel, get_checkout_attempts, get_checkout_summary

    try:
        days = request.args.get('days', type=int)
    except Exception:
        days = None

    return render_template(
        'admin/funnel.html',
        funnel=get_funnel(days),
        attempts=get_checkout_attempts(limit=25),
        checkout_summary=get_checkout_summary(),
        window_days=days,
    )


@admin_bp.route('/api/funnel')
@login_required
@admin_required
def api_funnel():
    """JSON funnel, for scripting or an external dashboard."""
    from services.funnel_analytics import get_funnel, get_checkout_summary

    days = request.args.get('days', type=int)
    return jsonify({
        'success': True,
        'funnel': get_funnel(days),
        'checkout': get_checkout_summary(),
    })


@admin_bp.route('/api/secrets/reload', methods=['POST'])
@login_required
@admin_required
def api_reload_secrets():
    """Re-read AWS Secrets Manager into the running process.

    init_secrets() only runs at startup, so a rotated credential used to require
    a redeploy — and until that happened the process kept serving the old value,
    making a fresh Stripe key look invalid. This closes that gap. Returns load
    state only; secret values are never included in the response.
    """
    from services.secrets_manager import reload_secrets

    try:
        state = reload_secrets()
    except Exception as e:
        logger.error("Secrets reload failed: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

    logger.info(
        "Secrets reloaded by admin %s: source=%s count=%s",
        current_user.id, state.get('source'), state.get('loaded_count')
    )
    return jsonify({
        'success': bool(state.get('reloaded')),
        'source': state.get('source'),
        'loaded_count': state.get('loaded_count'),
        'error': state.get('error'),
    })
