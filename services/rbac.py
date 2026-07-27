"""
Role-Based Access Control (RBAC) service for DevOps Agent.

Roles hierarchy (highest to lowest):
- admin: Full system access, user management, billing, all features
- approver: Can approve dangerous operations, manage team members
- user: Standard access to all features, can execute operations
- viewer: Read-only access, cannot execute operations

Permissions:
- read: View resources, dashboards, logs
- write: Create/modify resources, execute commands
- delete: Remove resources
- approve: Approve dangerous operations
- manage_users: Create/edit/delete users
- manage_billing: Access billing and subscription features
- manage_settings: Modify system settings
- execute_dangerous: Execute potentially dangerous operations
"""

from functools import wraps
from flask import abort, flash, redirect, url_for, request, jsonify
from flask_login import current_user
from enum import Enum
from typing import List, Set, Optional, Callable
import logging

logger = logging.getLogger(__name__)


class Role(Enum):
    """User roles with hierarchy levels."""
    ADMIN = 'admin'
    APPROVER = 'approver'
    USER = 'user'
    VIEWER = 'viewer'


class Permission(Enum):
    """Available permissions."""
    READ = 'read'
    WRITE = 'write'
    DELETE = 'delete'
    APPROVE = 'approve'
    MANAGE_USERS = 'manage_users'
    MANAGE_BILLING = 'manage_billing'
    MANAGE_SETTINGS = 'manage_settings'
    EXECUTE_DANGEROUS = 'execute_dangerous'
    MANAGE_TEAMS = 'manage_teams'
    VIEW_AUDIT_LOGS = 'view_audit_logs'
    MANAGE_API_KEYS = 'manage_api_keys'
    MANAGE_CREDENTIALS = 'manage_credentials'


# Role hierarchy - higher number = more privileges
ROLE_HIERARCHY = {
    Role.ADMIN.value: 100,
    Role.APPROVER.value: 75,
    Role.USER.value: 50,
    Role.VIEWER.value: 25
}

# Permissions granted to each role
ROLE_PERMISSIONS = {
    Role.ADMIN.value: {
        Permission.READ,
        Permission.WRITE,
        Permission.DELETE,
        Permission.APPROVE,
        Permission.MANAGE_USERS,
        Permission.MANAGE_BILLING,
        Permission.MANAGE_SETTINGS,
        Permission.EXECUTE_DANGEROUS,
        Permission.MANAGE_TEAMS,
        Permission.VIEW_AUDIT_LOGS,
        Permission.MANAGE_API_KEYS,
        Permission.MANAGE_CREDENTIALS
    },
    Role.APPROVER.value: {
        Permission.READ,
        Permission.WRITE,
        Permission.DELETE,
        Permission.APPROVE,
        Permission.MANAGE_TEAMS,
        Permission.VIEW_AUDIT_LOGS,
        Permission.MANAGE_API_KEYS,
        Permission.MANAGE_CREDENTIALS
    },
    Role.USER.value: {
        Permission.READ,
        Permission.WRITE,
        Permission.MANAGE_API_KEYS,
        Permission.MANAGE_CREDENTIALS
    },
    Role.VIEWER.value: {
        Permission.READ
    }
}


def get_user_role(user) -> str:
    """Get user's role, defaulting to 'user' if not set."""
    if not user or not hasattr(user, 'role'):
        return Role.USER.value
    return user.role or Role.USER.value


def get_role_level(role: str) -> int:
    """Get the hierarchy level of a role."""
    return ROLE_HIERARCHY.get(role, 0)


def get_role_permissions(role: str) -> Set[Permission]:
    """Get all permissions for a role."""
    return ROLE_PERMISSIONS.get(role, set())


def user_has_permission(user, permission: Permission) -> bool:
    """Check if user has a specific permission."""
    if not user or not user.is_authenticated:
        return False

    role = get_user_role(user)
    permissions = get_role_permissions(role)
    return permission in permissions


def user_has_role(user, required_role: str) -> bool:
    """Check if user has at least the required role level."""
    if not user or not user.is_authenticated:
        return False

    user_role = get_user_role(user)
    user_level = get_role_level(user_role)
    required_level = get_role_level(required_role)

    return user_level >= required_level


def user_is_admin(user) -> bool:
    """Check if user is an admin."""
    return user_has_role(user, Role.ADMIN.value)


def user_is_approver(user) -> bool:
    """Check if user is an approver or higher."""
    return user_has_role(user, Role.APPROVER.value)


def user_active_org_ids(user_id: int) -> Set[int]:
    """Organization IDs the user is an active member of (any org role).

    Shared by any route/service that scopes a non-admin approver's visibility to
    their own organization(s) — e.g. routes/changes.py's InfrastructureChange
    queries and services/approval_service.py's ApprovalRequest queries. Centralized
    here (rather than each call site reimplementing the same OrganizationMember
    lookup) after that duplication let approval_service.py's ApprovalRequest
    queries ship without the same org check changes.py already had, letting any
    role='approver' account approve/reject another organization's pending
    high-risk tool calls platform-wide.
    """
    from models import OrganizationMember
    rows = OrganizationMember.query.filter_by(
        user_id=user_id, is_active=True
    ).with_entities(OrganizationMember.organization_id).all()
    return {r[0] for r in rows}


def user_can_manage_user(manager, target_user) -> bool:
    """Check if manager can manage target user."""
    if not manager or not target_user:
        return False

    # Can't manage yourself (for role changes)
    if manager.id == target_user.id:
        return False

    # Must have manage_users permission
    if not user_has_permission(manager, Permission.MANAGE_USERS):
        return False

    # Can only manage users with lower role level
    manager_level = get_role_level(get_user_role(manager))
    target_level = get_role_level(get_user_role(target_user))

    return manager_level > target_level


# ==================== DECORATORS ====================


def require_role(role: str, redirect_to: str = None):
    """
    Decorator to require a minimum role level.

    Args:
        role: Minimum required role (admin, approver, user, viewer)
        redirect_to: URL to redirect on failure (for web routes)

    Usage:
        @require_role('admin')
        def admin_only_route():
            ...
    """
    def decorator(f: Callable):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                if redirect_to:
                    flash('Please log in to access this page.', 'warning')
                    return redirect(url_for('auth.login', next=request.url))
                return jsonify({'error': 'Authentication required'}), 401

            if not user_has_role(current_user, role):
                logger.warning(
                    f"Access denied: User {current_user.id} ({current_user.email}) "
                    f"with role '{get_user_role(current_user)}' attempted to access "
                    f"route requiring '{role}' role"
                )
                if redirect_to:
                    flash(f'Access denied. This page requires {role} privileges.', 'error')
                    return redirect(url_for(redirect_to))
                return jsonify({
                    'error': 'Access denied',
                    'message': f'This action requires {role} privileges',
                    'required_role': role,
                    'your_role': get_user_role(current_user)
                }), 403

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_permission(permission: Permission, redirect_to: str = None):
    """
    Decorator to require a specific permission.

    Args:
        permission: Required permission
        redirect_to: URL to redirect on failure (for web routes)

    Usage:
        @require_permission(Permission.MANAGE_USERS)
        def user_management_route():
            ...
    """
    def decorator(f: Callable):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                if redirect_to:
                    flash('Please log in to access this page.', 'warning')
                    return redirect(url_for('auth.login', next=request.url))
                return jsonify({'error': 'Authentication required'}), 401

            if not user_has_permission(current_user, permission):
                logger.warning(
                    f"Permission denied: User {current_user.id} ({current_user.email}) "
                    f"attempted action requiring '{permission.value}' permission"
                )
                if redirect_to:
                    flash(f'Access denied. You do not have {permission.value} permission.', 'error')
                    return redirect(url_for(redirect_to))
                return jsonify({
                    'error': 'Permission denied',
                    'message': f'This action requires {permission.value} permission',
                    'required_permission': permission.value
                }), 403

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def admin_required(f: Callable):
    """Shortcut decorator for admin-only routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login', next=request.url))

        if not user_is_admin(current_user):
            logger.warning(
                f"Admin access denied: User {current_user.id} ({current_user.email}) "
                f"with role '{get_user_role(current_user)}'"
            )
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({
                    'error': 'Admin access required',
                    'your_role': get_user_role(current_user)
                }), 403
            flash('Access denied. Administrator privileges required.', 'error')
            return redirect(url_for('dashboard'))

        return f(*args, **kwargs)
    return decorated_function


def approver_required(f: Callable):
    """Shortcut decorator for approver-or-higher routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login', next=request.url))

        if not user_is_approver(current_user):
            logger.warning(
                f"Approver access denied: User {current_user.id} ({current_user.email}) "
                f"with role '{get_user_role(current_user)}'"
            )
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({
                    'error': 'Approver access required',
                    'your_role': get_user_role(current_user)
                }), 403
            flash('Access denied. Approver privileges required.', 'error')
            return redirect(url_for('dashboard'))

        return f(*args, **kwargs)
    return decorated_function


def write_required(f: Callable):
    """Decorator for routes that modify data (not for viewers)."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login', next=request.url))

        if not user_has_permission(current_user, Permission.WRITE):
            logger.warning(
                f"Write access denied: User {current_user.id} ({current_user.email}) "
                f"with role '{get_user_role(current_user)}' (viewer)"
            )
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({
                    'error': 'Write access required',
                    'message': 'Viewers cannot perform this action',
                    'your_role': get_user_role(current_user)
                }), 403
            flash('Access denied. Viewers cannot perform this action.', 'error')
            return redirect(url_for('dashboard'))

        return f(*args, **kwargs)
    return decorated_function


# ==================== UTILITY FUNCTIONS ====================


def get_all_roles() -> List[dict]:
    """Get all available roles with their details."""
    return [
        {
            'name': Role.ADMIN.value,
            'display_name': 'Administrator',
            'description': 'Full system access, user management, billing',
            'level': ROLE_HIERARCHY[Role.ADMIN.value],
            'permissions': [p.value for p in ROLE_PERMISSIONS[Role.ADMIN.value]]
        },
        {
            'name': Role.APPROVER.value,
            'display_name': 'Approver',
            'description': 'Can approve operations, manage team members',
            'level': ROLE_HIERARCHY[Role.APPROVER.value],
            'permissions': [p.value for p in ROLE_PERMISSIONS[Role.APPROVER.value]]
        },
        {
            'name': Role.USER.value,
            'display_name': 'User',
            'description': 'Standard access to all features',
            'level': ROLE_HIERARCHY[Role.USER.value],
            'permissions': [p.value for p in ROLE_PERMISSIONS[Role.USER.value]]
        },
        {
            'name': Role.VIEWER.value,
            'display_name': 'Viewer',
            'description': 'Read-only access',
            'level': ROLE_HIERARCHY[Role.VIEWER.value],
            'permissions': [p.value for p in ROLE_PERMISSIONS[Role.VIEWER.value]]
        }
    ]


def get_assignable_roles(manager) -> List[dict]:
    """Get roles that a manager can assign to users."""
    if not manager or not user_has_permission(manager, Permission.MANAGE_USERS):
        return []

    manager_level = get_role_level(get_user_role(manager))

    # Can only assign roles lower than your own
    return [
        role for role in get_all_roles()
        if role['level'] < manager_level
    ]


def check_operation_approval(user, operation_type: str) -> dict:
    """
    Check if an operation requires approval and if user can execute it.

    Args:
        user: Current user
        operation_type: Type of operation (e.g., 'delete_resource', 'modify_production')

    Returns:
        dict with 'allowed', 'requires_approval', 'message'
    """
    dangerous_operations = {
        'delete_resource': 'Deleting resources',
        'modify_production': 'Modifying production environment',
        'execute_script': 'Executing scripts',
        'terraform_destroy': 'Terraform destroy',
        'ansible_playbook': 'Running Ansible playbooks',
        'kubernetes_delete': 'Deleting Kubernetes resources',
        'database_modify': 'Modifying database',
        'security_change': 'Changing security settings'
    }

    if operation_type not in dangerous_operations:
        return {
            'allowed': user_has_permission(user, Permission.WRITE),
            'requires_approval': False,
            'message': 'Standard operation'
        }

    # Check if user can execute dangerous operations
    if user_has_permission(user, Permission.EXECUTE_DANGEROUS):
        return {
            'allowed': True,
            'requires_approval': False,
            'message': 'User has dangerous operation privileges'
        }

    # Check if user can approve (and thus execute)
    if user_has_permission(user, Permission.APPROVE):
        return {
            'allowed': True,
            'requires_approval': False,
            'message': 'User has approval privileges'
        }

    # User needs approval
    if user_has_permission(user, Permission.WRITE):
        return {
            'allowed': False,
            'requires_approval': True,
            'message': f'{dangerous_operations[operation_type]} requires approval from an approver or admin'
        }

    return {
        'allowed': False,
        'requires_approval': False,
        'message': 'Insufficient permissions'
    }


class RBACContext:
    """Context manager for RBAC checks in templates."""

    def __init__(self, user):
        self.user = user

    @property
    def role(self) -> str:
        return get_user_role(self.user)

    @property
    def is_admin(self) -> bool:
        return user_is_admin(self.user)

    @property
    def is_approver(self) -> bool:
        return user_is_approver(self.user)

    @property
    def is_viewer(self) -> bool:
        return self.role == Role.VIEWER.value

    @property
    def can_write(self) -> bool:
        return user_has_permission(self.user, Permission.WRITE)

    @property
    def can_delete(self) -> bool:
        return user_has_permission(self.user, Permission.DELETE)

    @property
    def can_manage_users(self) -> bool:
        return user_has_permission(self.user, Permission.MANAGE_USERS)

    @property
    def can_manage_billing(self) -> bool:
        return user_has_permission(self.user, Permission.MANAGE_BILLING)

    @property
    def can_approve(self) -> bool:
        return user_has_permission(self.user, Permission.APPROVE)

    def has_permission(self, permission_name: str) -> bool:
        try:
            permission = Permission(permission_name)
            return user_has_permission(self.user, permission)
        except ValueError:
            return False

    def has_role(self, role_name: str) -> bool:
        return user_has_role(self.user, role_name)
