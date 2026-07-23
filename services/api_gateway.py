"""
API Gateway Service for DevOps Agent.

Provides public API access, API key management, rate limiting, and webhooks out.
Uses database persistence for all data.
"""

import ipaddress
import logging
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime, timedelta, date
from enum import Enum
import secrets
import hashlib
import hmac
import json
import socket
from urllib.parse import urlparse
from functools import wraps

from flask import request, jsonify, g

logger = logging.getLogger(__name__)


def _is_safe_webhook_url(url: str) -> bool:
    """Block webhook URLs targeting internal/private networks (SSRF protection)."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        resolved = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in resolved:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        return True
    except Exception:
        return False


class APIKeyScope(Enum):
    """API key permission scopes."""
    READ = 'read'
    WRITE = 'write'
    DELETE = 'delete'
    ADMIN = 'admin'


class RateLimitTier(Enum):
    """Rate limit tiers."""
    FREE = 'free'
    STANDARD = 'standard'
    PREMIUM = 'premium'
    ENTERPRISE = 'enterprise'


class WebhookEvent(Enum):
    """Webhook event types."""
    RESOURCE_CREATED = 'resource.created'
    RESOURCE_UPDATED = 'resource.updated'
    RESOURCE_DELETED = 'resource.deleted'
    INCIDENT_CREATED = 'incident.created'
    INCIDENT_RESOLVED = 'incident.resolved'
    ALERT_TRIGGERED = 'alert.triggered'
    DEPLOYMENT_STARTED = 'deployment.started'
    DEPLOYMENT_COMPLETED = 'deployment.completed'
    COST_ANOMALY = 'cost.anomaly'
    SECURITY_FINDING = 'security.finding'


RATE_LIMITS = {
    RateLimitTier.FREE: {'requests_per_minute': 60, 'requests_per_day': 1000},
    RateLimitTier.STANDARD: {'requests_per_minute': 300, 'requests_per_day': 10000},
    RateLimitTier.PREMIUM: {'requests_per_minute': 1000, 'requests_per_day': 100000},
    RateLimitTier.ENTERPRISE: {'requests_per_minute': 5000, 'requests_per_day': 1000000}
}


class APIGatewayService:
    """API Gateway service with database persistence."""

    def __init__(self, user_id: Optional[int] = None):
        self.user_id = user_id
        self._rate_limit_cache: Dict[int, Dict] = {}

    def _get_db(self):
        """Get database session."""
        from models import db
        return db

    def _get_api_key_model(self):
        """Get APIKey model."""
        from models import APIKey
        return APIKey

    def _get_webhook_model(self):
        """Get WebhookEndpoint model."""
        from models import WebhookEndpoint
        return WebhookEndpoint

    def _get_delivery_model(self):
        """Get WebhookDelivery model."""
        from models import WebhookDelivery
        return WebhookDelivery

    # API Key Management

    def create_api_key(self, user_id: int, name: str, scopes: List[str],
                       expires_in_days: Optional[int] = None) -> tuple:
        """Create a new API key. Returns (api_key_model, plain_key)."""
        APIKey = self._get_api_key_model()
        db = self._get_db()

        api_key, plain_key = APIKey.create_for_user(user_id, name, scopes)

        if expires_in_days:
            api_key.expires_at = datetime.utcnow() + timedelta(days=expires_in_days)

        db.session.add(api_key)
        db.session.commit()

        logger.info(f"Created API key: {name} for user {user_id}")
        return api_key, plain_key

    def get_api_key(self, key_id: int) -> Optional[Any]:
        """Get API key by ID."""
        APIKey = self._get_api_key_model()
        return APIKey.query.get(key_id)

    def get_api_key_by_key(self, key: str) -> Optional[Any]:
        """Get API key by the actual key value."""
        APIKey = self._get_api_key_model()
        return APIKey.verify_key(key)

    def get_user_api_keys(self, user_id: int) -> List[Any]:
        """Get all API keys for a user."""
        APIKey = self._get_api_key_model()
        return APIKey.query.filter_by(user_id=user_id, is_active=True).all()

    def revoke_api_key(self, key_id: int, user_id: int) -> bool:
        """Revoke an API key (user_id enforces ownership)."""
        APIKey = self._get_api_key_model()
        api_key = APIKey.query.filter_by(id=key_id, user_id=user_id).first()
        if api_key:
            api_key.revoke()
            logger.info(f"Revoked API key: {api_key.name}")
            return True
        return False

    def rotate_api_key(self, key_id: int, user_id: Optional[int] = None) -> Optional[tuple]:
        """Rotate an API key (create new, revoke old).

        When user_id is given, only the owner may rotate the key.
        """
        old_key = self.get_api_key(key_id)
        if not old_key or (user_id is not None and old_key.user_id != user_id):
            return None

        # Create new key with same settings
        new_key, plain_key = self.create_api_key(
            old_key.user_id,
            f"{old_key.name} (rotated)",
            old_key.scopes or ['read']
        )
        new_key.rate_limit = old_key.rate_limit

        # Revoke old key (scoped to the owner — revoke_api_key requires user_id)
        self.revoke_api_key(key_id, old_key.user_id)

        return new_key, plain_key

    # Authentication & Authorization

    def authenticate_request(self) -> tuple:
        """Authenticate an API request."""
        auth_header = request.headers.get('Authorization', '')
        api_key_header = request.headers.get('X-API-Key', '')

        key_value = None
        if auth_header.startswith('Bearer '):
            key_value = auth_header[7:]
        elif api_key_header:
            key_value = api_key_header

        if not key_value:
            return None, {'error': 'API key required', 'code': 'missing_key'}

        api_key = self.get_api_key_by_key(key_value)
        if not api_key:
            return None, {'error': 'Invalid API key', 'code': 'invalid_key'}

        if not api_key.is_active:
            return None, {'error': 'API key revoked', 'code': 'revoked_key'}

        if api_key.expires_at and datetime.utcnow() > api_key.expires_at:
            return None, {'error': 'API key expired', 'code': 'expired_key'}

        # Update last used
        db = self._get_db()
        api_key.last_used_at = datetime.utcnow()
        api_key.last_used_ip = request.remote_addr
        db.session.commit()

        return api_key, None

    def check_rate_limit(self, api_key) -> tuple:
        """Check rate limit for an API key."""
        db = self._get_db()
        today = date.today()

        # Reset daily counter if new day
        if api_key.last_request_date != today:
            api_key.requests_today = 0
            api_key.last_request_date = today

        # Check rate limit
        rate_limit = api_key.rate_limit or 1000
        if api_key.requests_today >= rate_limit:
            return False, {
                'error': 'Rate limit exceeded',
                'limit': rate_limit,
                'retry_after': 3600
            }

        # Increment counter
        api_key.requests_today += 1
        api_key.total_requests += 1
        db.session.commit()

        return True, {
            'remaining': rate_limit - api_key.requests_today,
            'limit': rate_limit
        }

    def check_scope(self, api_key, required_scope: str) -> bool:
        """Check if API key has required scope."""
        return api_key.has_scope(required_scope)

    # Webhook Management

    def create_webhook(self, user_id: int, name: str, url: str,
                       events: List[str]) -> Any:
        """Create a webhook endpoint."""
        WebhookEndpoint = self._get_webhook_model()
        db = self._get_db()

        webhook = WebhookEndpoint(
            user_id=user_id,
            name=name,
            url=url,
            secret=secrets.token_urlsafe(32),
            events=events,
            is_active=True
        )

        db.session.add(webhook)
        db.session.commit()

        logger.info(f"Created webhook: {url} for events {events}")
        return webhook

    def get_webhook(self, webhook_id: int) -> Optional[Any]:
        """Get webhook by ID."""
        WebhookEndpoint = self._get_webhook_model()
        return WebhookEndpoint.query.get(webhook_id)

    def get_user_webhooks(self, user_id: int) -> List[Any]:
        """Get all webhooks for a user."""
        WebhookEndpoint = self._get_webhook_model()
        return WebhookEndpoint.query.filter_by(user_id=user_id).all()

    def update_webhook(self, webhook_id: int, updates: Dict) -> Optional[Any]:
        """Update a webhook."""
        db = self._get_db()
        webhook = self.get_webhook(webhook_id)
        if not webhook:
            return None

        if 'url' in updates:
            webhook.url = updates['url']
        if 'events' in updates:
            webhook.events = updates['events']
        if 'is_active' in updates:
            webhook.is_active = updates['is_active']
        if 'name' in updates:
            webhook.name = updates['name']

        db.session.commit()
        return webhook

    def delete_webhook(self, webhook_id: int, user_id: Optional[int] = None) -> bool:
        """Delete a webhook. When user_id is given, only the owner may delete it."""
        db = self._get_db()
        webhook = self.get_webhook(webhook_id)
        if not webhook or (user_id is not None and webhook.user_id != user_id):
            return False
        db.session.delete(webhook)
        db.session.commit()
        return True

    def toggle_webhook(self, webhook_id: int, user_id: Optional[int] = None) -> Optional[Any]:
        """Toggle webhook active state. When user_id is given, owner-only."""
        db = self._get_db()
        webhook = self.get_webhook(webhook_id)
        if not webhook or (user_id is not None and webhook.user_id != user_id):
            return None
        webhook.is_active = not webhook.is_active
        db.session.commit()
        return webhook

    def trigger_webhook(self, event: str, payload: Dict, user_id: Optional[int] = None):
        """Trigger webhooks for an event."""
        import requests as http_requests
        WebhookDelivery = self._get_delivery_model()
        db = self._get_db()

        webhooks = self.get_user_webhooks(user_id) if user_id else []

        for webhook in webhooks:
            if not webhook.is_active:
                continue
            if event not in (webhook.events or []):
                continue

            delivery = WebhookDelivery(
                endpoint_id=webhook.id,
                event_type=event,
                payload=payload,
                status='pending'
            )
            db.session.add(delivery)

            # Create signature
            signature_payload = json.dumps(payload, sort_keys=True)
            signature = hmac.new(
                (webhook.secret or '').encode(),
                signature_payload.encode(),
                hashlib.sha256
            ).hexdigest()

            headers = {
                'Content-Type': 'application/json',
                'X-DevOps-Agent-Event': event,
                'X-DevOps-Agent-Signature': f"sha256={signature}",
                'X-DevOps-Agent-Delivery': str(delivery.id) if delivery.id else 'new'
            }

            try:
                if not _is_safe_webhook_url(webhook.url):
                    delivery.status = 'failed'
                    delivery.response_body = 'Webhook URL targets a private/internal network (blocked by SSRF protection)'
                    db.session.commit()
                    logger.warning(f"Blocked SSRF attempt to {webhook.url}")
                    return delivery
                start_time = datetime.utcnow()
                response = http_requests.post(
                    webhook.url,
                    json=payload,
                    headers=headers,
                    timeout=webhook.timeout_seconds or 30
                )
                duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

                delivery.response_status_code = response.status_code
                delivery.response_body = response.text[:1000]
                delivery.status = 'success' if 200 <= response.status_code < 300 else 'failed'
                delivery.delivered_at = datetime.utcnow()

                if delivery.status == 'success':
                    webhook.successful_deliveries += 1
                else:
                    webhook.failed_deliveries += 1

            except Exception as e:
                delivery.status = 'failed'
                delivery.error_message = str(e)
                webhook.failed_deliveries += 1
                logger.error(f"Webhook delivery failed: {e}")

            webhook.total_deliveries += 1
            webhook.last_delivery_at = datetime.utcnow()
            webhook.last_delivery_status = delivery.status

            db.session.commit()

    def test_webhook(self, webhook_id: int, user_id: Optional[int] = None) -> Dict:
        """Send a test event to a webhook. When user_id is given, owner-only."""
        webhook = self.get_webhook(webhook_id)
        if not webhook or (user_id is not None and webhook.user_id != user_id):
            return {'success': False, 'error': 'Webhook not found'}

        test_payload = {
            'event': 'test',
            'timestamp': datetime.utcnow().isoformat(),
            'message': 'This is a test webhook delivery'
        }

        import requests as http_requests

        if not _is_safe_webhook_url(webhook.url):
            logger.warning(f"Blocked SSRF attempt in test_webhook to {webhook.url}")
            return {'success': False, 'error': 'Webhook URL targets a private/internal network (blocked by SSRF protection)'}

        try:
            signature_payload = json.dumps(test_payload, sort_keys=True)
            signature = hmac.new(
                (webhook.secret or '').encode(),
                signature_payload.encode(),
                hashlib.sha256
            ).hexdigest()

            response = http_requests.post(
                webhook.url,
                json=test_payload,
                headers={
                    'Content-Type': 'application/json',
                    'X-DevOps-Agent-Event': 'test',
                    'X-DevOps-Agent-Signature': f"sha256={signature}"
                },
                timeout=10
            )

            return {
                'success': 200 <= response.status_code < 300,
                'status_code': response.status_code,
                'response': response.text[:500]
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_webhook_deliveries(self, webhook_id: int, limit: int = 50) -> List[Any]:
        """Get recent deliveries for a webhook."""
        WebhookDelivery = self._get_delivery_model()
        return WebhookDelivery.query.filter_by(endpoint_id=webhook_id)\
            .order_by(WebhookDelivery.created_at.desc())\
            .limit(limit).all()

    # API Usage Stats

    def get_api_usage_stats(self, user_id: int) -> Dict:
        """Get API usage statistics for a user."""
        user_keys = self.get_user_api_keys(user_id)

        total_requests = 0
        by_key = {}

        for key in user_keys:
            total_requests += key.total_requests or 0
            by_key[key.name] = {
                'requests_today': key.requests_today or 0,
                'total_requests': key.total_requests or 0,
                'last_used': key.last_used_at.isoformat() if key.last_used_at else None
            }

        return {
            'total_requests': total_requests,
            'requests_today': sum(k.requests_today or 0 for k in user_keys),
            'by_key': by_key,
            'active_keys': len(user_keys)
        }

    def get_webhook_stats(self, user_id: int) -> Dict:
        """Get webhook statistics for a user."""
        user_webhooks = self.get_user_webhooks(user_id)

        total_deliveries = sum(w.total_deliveries or 0 for w in user_webhooks)
        successful = sum(w.successful_deliveries or 0 for w in user_webhooks)

        return {
            'total_webhooks': len(user_webhooks),
            'active_webhooks': len([w for w in user_webhooks if w.is_active]),
            'total_deliveries': total_deliveries,
            'successful_deliveries': successful,
            'success_rate': (successful / total_deliveries * 100) if total_deliveries > 0 else 100
        }


# Factory function
def get_api_gateway_service(user_id: Optional[int] = None) -> APIGatewayService:
    """Get API gateway service instance."""
    return APIGatewayService(user_id)


# Decorators for API routes

def require_api_key(scopes: List[str] = None):
    """Decorator to require API key authentication."""
    def decorator(f: Callable):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            service = get_api_gateway_service()

            # Authenticate
            api_key, error = service.authenticate_request()
            if error:
                return jsonify(error), 401

            # Check rate limit
            allowed, rate_info = service.check_rate_limit(api_key)
            if not allowed:
                return jsonify(rate_info), 429

            # Check scopes
            if scopes:
                for scope in scopes:
                    if not service.check_scope(api_key, scope):
                        return jsonify({
                            'error': 'Insufficient permissions',
                            'required_scope': scope
                        }), 403

            # Add API key to request context
            g.api_key = api_key
            g.rate_limit_info = rate_info

            return f(*args, **kwargs)
        return decorated_function
    return decorator
