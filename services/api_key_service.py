"""
API Key Management Service

Provides API key generation, validation, and management for programmatic access.
"""

import logging
import secrets
import hashlib
from typing import Optional, Tuple, List
from datetime import datetime, timedelta
from functools import wraps

from flask import request, jsonify, g

logger = logging.getLogger(__name__)

# API Key format: doa_{env}_{random}
# Example: doa_live_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
KEY_PREFIX = "doa"
KEY_LENGTH = 32  # Random part length in hex (16 bytes = 32 hex chars)


class APIKeyService:
    """
    Service for managing API keys.

    Features:
    - Secure key generation
    - Key validation with rate limiting
    - Scope-based permissions
    - IP whitelist support
    - Usage tracking
    """

    def __init__(self, app=None):
        if app:
            self.init_app(app)

    def init_app(self, app):
        """Initialize with Flask app."""
        app.extensions = getattr(app, 'extensions', {})
        app.extensions['api_key'] = self

    def generate_key(self, environment: str = 'live') -> str:
        """
        Generate a new API key.

        Args:
            environment: 'live' or 'test'

        Returns:
            Plain text API key (only shown once)
        """
        random_part = secrets.token_hex(KEY_LENGTH // 2)
        return f"{KEY_PREFIX}_{environment}_{random_part}"

    def hash_key(self, key: str) -> str:
        """
        Hash an API key for secure storage.

        Args:
            key: Plain text API key

        Returns:
            SHA-256 hash of the key
        """
        return hashlib.sha256(key.encode()).hexdigest()

    def get_key_prefix(self, key: str) -> str:
        """Extract the prefix portion of the key for identification."""
        return key[:12] if len(key) >= 12 else key

    def create_key(self, user_id: int, name: str, scopes: List[str] = None,
                   expires_days: int = None, allowed_ips: List[str] = None,
                   rate_limit: int = 1000) -> Tuple[object, str]:
        """
        Create a new API key for a user.

        Args:
            user_id: User ID
            name: Friendly name for the key
            scopes: List of permission scopes
            expires_days: Days until expiration (None = no expiration)
            allowed_ips: List of allowed IP addresses
            rate_limit: Requests per hour limit

        Returns:
            Tuple of (APIKey model, plain text key)
        """
        from models import APIKey, db

        # Generate key
        key = self.generate_key()

        # Calculate expiration
        expires_at = None
        if expires_days:
            expires_at = datetime.utcnow() + timedelta(days=expires_days)

        # Create model
        api_key = APIKey(
            user_id=user_id,
            name=name,
            key_prefix=self.get_key_prefix(key),
            key_hash=self.hash_key(key),
            scopes=scopes or ['read'],
            allowed_ips=allowed_ips or [],
            rate_limit=rate_limit,
            expires_at=expires_at
        )

        db.session.add(api_key)
        db.session.commit()

        logger.info(f"Created API key '{name}' for user {user_id}")
        return api_key, key

    def validate_key(self, key: str, required_scope: str = None,
                     ip_address: str = None) -> Tuple[bool, Optional[object], str]:
        """
        Validate an API key.

        Args:
            key: Plain text API key
            required_scope: Required permission scope
            ip_address: Client IP address for whitelist check

        Returns:
            Tuple of (is_valid, APIKey model or None, error message)
        """
        from models import APIKey, db

        if not key or not key.startswith(KEY_PREFIX):
            return False, None, "Invalid API key format"

        # Find key by hash
        key_hash = self.hash_key(key)
        api_key = APIKey.query.filter_by(key_hash=key_hash).first()

        if not api_key:
            return False, None, "API key not found"

        if not api_key.is_active:
            return False, None, "API key is revoked"

        # Check expiration
        if api_key.expires_at and api_key.expires_at < datetime.utcnow():
            return False, None, "API key has expired"

        # Check IP whitelist
        if api_key.allowed_ips and ip_address:
            if ip_address not in api_key.allowed_ips:
                return False, None, "IP address not allowed"

        # Check scope
        if required_scope and not api_key.has_scope(required_scope):
            return False, None, f"Missing required scope: {required_scope}"

        # Check rate limit
        today = datetime.utcnow().date()
        if api_key.last_request_date != today:
            api_key.requests_today = 0
            api_key.last_request_date = today

        if api_key.requests_today >= api_key.rate_limit:
            return False, None, "Rate limit exceeded"

        # Update usage stats
        api_key.last_used_at = datetime.utcnow()
        api_key.last_used_ip = ip_address
        api_key.total_requests += 1
        api_key.requests_today += 1
        db.session.commit()

        return True, api_key, ""

    def revoke_key(self, key_id: int, user_id: int) -> bool:
        """
        Revoke an API key.

        Args:
            key_id: API key ID
            user_id: Owner user ID (for authorization)

        Returns:
            True if revoked successfully
        """
        from models import APIKey, db

        api_key = APIKey.query.filter_by(id=key_id, user_id=user_id).first()
        if not api_key:
            return False

        api_key.is_active = False
        api_key.revoked_at = datetime.utcnow()
        db.session.commit()

        logger.info(f"Revoked API key {key_id} for user {user_id}")
        return True

    def list_user_keys(self, user_id: int, include_revoked: bool = False) -> List[object]:
        """
        List all API keys for a user.

        Args:
            user_id: User ID
            include_revoked: Whether to include revoked keys

        Returns:
            List of APIKey models
        """
        from models import APIKey

        query = APIKey.query.filter_by(user_id=user_id)
        if not include_revoked:
            query = query.filter_by(is_active=True)

        return query.order_by(APIKey.created_at.desc()).all()

    def rotate_key(self, key_id: int, user_id: int) -> Tuple[Optional[object], str]:
        """
        Rotate an API key (revoke old, create new with same settings).

        Args:
            key_id: API key ID to rotate
            user_id: Owner user ID

        Returns:
            Tuple of (new APIKey model, new plain text key) or (None, error)
        """
        from models import APIKey

        old_key = APIKey.query.filter_by(id=key_id, user_id=user_id, is_active=True).first()
        if not old_key:
            return None, "API key not found"

        # Create new key with same settings
        new_api_key, new_key = self.create_key(
            user_id=user_id,
            name=f"{old_key.name} (rotated)",
            scopes=old_key.scopes,
            allowed_ips=old_key.allowed_ips,
            rate_limit=old_key.rate_limit
        )

        # Revoke old key
        self.revoke_key(key_id, user_id)

        logger.info(f"Rotated API key {key_id} for user {user_id}")
        return new_api_key, new_key


# Global service instance
api_key_service = APIKeyService()


def init_api_key_service(app):
    """Initialize API key service with Flask app."""
    api_key_service.init_app(app)
    return api_key_service


# ==========================================
# Decorator for API key authentication
# ==========================================

def require_api_key(scope: str = None):
    """
    Decorator to require API key authentication.

    Usage:
        @app.route('/api/v1/resources')
        @require_api_key(scope='read')
        def list_resources():
            user = g.api_user  # Access authenticated user
            ...

    Args:
        scope: Required permission scope
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Get API key from header
            auth_header = request.headers.get('Authorization', '')
            api_key = None

            if auth_header.startswith('Bearer '):
                api_key = auth_header[7:]
            elif auth_header.startswith('Api-Key '):
                api_key = auth_header[8:]

            # Also check X-API-Key header
            if not api_key:
                api_key = request.headers.get('X-API-Key')

            if not api_key:
                return jsonify({
                    'error': 'Missing API key',
                    'message': 'Provide API key via Authorization: Bearer <key> or X-API-Key header'
                }), 401

            # Validate key
            ip_address = request.remote_addr
            is_valid, key_obj, error = api_key_service.validate_key(
                api_key, required_scope=scope, ip_address=ip_address
            )

            if not is_valid:
                return jsonify({
                    'error': 'Invalid API key',
                    'message': error
                }), 401

            # Store user and key in g for access in route
            from models import User
            g.api_key = key_obj
            g.api_user = User.query.get(key_obj.user_id)

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def optional_api_key():
    """
    Decorator for routes that accept but don't require API key.

    Sets g.api_key and g.api_user if valid key provided, otherwise None.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            g.api_key = None
            g.api_user = None

            # Get API key from header
            auth_header = request.headers.get('Authorization', '')
            api_key = None

            if auth_header.startswith('Bearer '):
                api_key = auth_header[7:]
            elif auth_header.startswith('Api-Key '):
                api_key = auth_header[8:]

            if not api_key:
                api_key = request.headers.get('X-API-Key')

            if api_key:
                ip_address = request.remote_addr
                is_valid, key_obj, _ = api_key_service.validate_key(
                    api_key, ip_address=ip_address
                )

                if is_valid:
                    from models import User
                    g.api_key = key_obj
                    g.api_user = User.query.get(key_obj.user_id)

            return f(*args, **kwargs)
        return decorated_function
    return decorator
