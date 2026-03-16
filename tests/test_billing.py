"""
Billing Blueprint Tests

Tests for billing routes, NGN price helper, and Stripe webhook handling.
"""
import json
from unittest.mock import MagicMock, patch


# ==================== _get_ngn_price_id helper ====================


class TestGetNgnPriceId:
    """Unit tests for the _get_ngn_price_id() helper in routes/billing.py."""

    def test_returns_price_id_when_configured(self, app, db_session):
        """Returns Stripe price ID when a matching NGNPriceConfig row exists."""
        from routes.billing import _get_ngn_price_id
        from models import db, NGNPriceConfig

        config = NGNPriceConfig(
            product_key='starter',
            product_type='subscription',
            price_ngn=15000,
            stripe_price_id_ngn='price_ngn_test_123',
            is_active=True,
        )
        db.session.add(config)
        db.session.commit()

        result = _get_ngn_price_id('starter', 'subscription')
        assert result == 'price_ngn_test_123'

        db.session.delete(config)
        db.session.commit()

    def test_returns_none_when_not_configured(self, app, db_session):
        """Returns None when no matching NGNPriceConfig row exists."""
        from routes.billing import _get_ngn_price_id

        result = _get_ngn_price_id('nonexistent_product', 'subscription')
        assert result is None

    def test_returns_none_when_stripe_price_id_missing(self, app, db_session):
        """Returns None when config row exists but stripe_price_id_ngn is empty."""
        from routes.billing import _get_ngn_price_id
        from models import db, NGNPriceConfig

        config = NGNPriceConfig(
            product_key='pack_100',
            product_type='credit_pack',
            price_ngn=5000,
            stripe_price_id_ngn=None,
            is_active=True,
        )
        db.session.add(config)
        db.session.commit()

        result = _get_ngn_price_id('pack_100', 'credit_pack')
        assert result is None

        db.session.delete(config)
        db.session.commit()


# ==================== Billing page routes ====================


class TestBillingPageRoutes:
    """Tests for billing page and success page."""

    def test_billing_requires_auth(self, client):
        """GET /billing redirects unauthenticated users."""
        response = client.get('/billing')
        assert response.status_code in [302, 401]

    def test_billing_success_requires_auth(self, client):
        """GET /billing/success redirects unauthenticated users."""
        response = client.get('/billing/success')
        assert response.status_code in [302, 401]

    def test_billing_page_loads(self, authenticated_client):
        """GET /billing returns 200 for authenticated users."""
        response = authenticated_client.get('/billing')
        assert response.status_code == 200


# ==================== Stripe webhook ====================


class TestStripeWebhook:
    """Integration tests for the /api/stripe/webhook route."""

    def test_webhook_rejects_invalid_signature(self, client):
        """POST with an invalid Stripe signature returns 400."""
        from routes.billing import STRIPE_ENABLED
        if not STRIPE_ENABLED:
            return  # Skip if Stripe not installed

        with patch('routes.billing.StripePaymentService.construct_webhook_event',
                   side_effect=ValueError('Invalid signature')):
            response = client.post(
                '/api/stripe/webhook',
                data=b'{"id": "evt_test"}',
                headers={'Stripe-Signature': 'bad_sig', 'Content-Type': 'application/json'},
            )
        assert response.status_code == 400

    def test_webhook_processes_checkout_completed(self, client, app):
        """POST with a valid checkout.session.completed event calls handle_checkout_completed."""
        from routes.billing import STRIPE_ENABLED
        if not STRIPE_ENABLED:
            return

        fake_event = {
            'id': 'evt_test_checkout_001',
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'customer_email': None,
                    'metadata': {'product_type': 'subscription', 'user_id': '999'},
                    'customer': None,
                }
            }
        }

        with patch('routes.billing.StripePaymentService.construct_webhook_event',
                   return_value=fake_event), \
             patch('routes.billing.handle_checkout_completed') as mock_handler:
            response = client.post(
                '/api/stripe/webhook',
                data=b'{}',
                headers={'Stripe-Signature': 'test_sig'},
            )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        mock_handler.assert_called_once()

    def test_webhook_skips_duplicate_events(self, client, app, db_session):
        """POST with an already-processed event ID returns success with duplicate=True."""
        from routes.billing import STRIPE_ENABLED
        if not STRIPE_ENABLED:
            return
        from models import db, PaymentWebhookEvent

        # Pre-insert the idempotency record in the existing app context
        existing = PaymentWebhookEvent(
            id='stripe:evt_dup_test_001',
            gateway='stripe',
            event_type='checkout.session.completed',
        )
        db.session.add(existing)
        db.session.commit()

        fake_event = {
            'id': 'evt_dup_test_001',
            'type': 'checkout.session.completed',
            'data': {'object': {}}
        }

        with patch('routes.billing.StripePaymentService.construct_webhook_event',
                   return_value=fake_event), \
             patch('routes.billing.handle_checkout_completed') as mock_handler:
            response = client.post(
                '/api/stripe/webhook',
                data=b'{}',
                headers={'Stripe-Signature': 'test_sig'},
            )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data.get('duplicate') is True
        mock_handler.assert_not_called()

        # Cleanup
        rec = PaymentWebhookEvent.query.get('stripe:evt_dup_test_001')
        if rec:
            db.session.delete(rec)
            db.session.commit()
