"""
Payment Credit Tests

Verifies that subscribing / purchasing credits always lands the correct
credits on the user's account — covering new subscribers, upgrades,
credit packs, idempotency, and error paths.
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tier(db, name, credits, price=29.0):
    """Get-or-create a SubscriptionTier row."""
    from models import SubscriptionTier
    tier = SubscriptionTier.query.filter_by(name=name).first()
    if not tier:
        tier = SubscriptionTier(
            name=name,
            display_name=name.capitalize(),
            monthly_credits=credits,
            monthly_price=price,
        )
        db.session.add(tier)
        db.session.commit()
    return tier


def _make_user(db, email='pay_test@example.com'):
    """Get-or-create a User row."""
    from models import User
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(email=email, username=email.split('@')[0], full_name='Pay Test')
        user.set_password('Test1234!')
        db.session.add(user)
        db.session.commit()
    return user


def _checkout_session(user_id, tier_name, customer='cus_test123',
                      subscription_id='sub_test123', product_type='subscription'):
    """Build a minimal Stripe checkout.session.completed payload."""
    return {
        'customer': customer,
        'customer_email': None,
        'subscription': subscription_id,
        'metadata': {
            'user_id': str(user_id),
            'tier_name': tier_name,
            'product_type': product_type,
        },
    }


def _credit_pack_session(user_id, pack_size, customer='cus_test123'):
    """Build a minimal Stripe checkout payload for a credit pack."""
    return {
        'customer': customer,
        'customer_email': None,
        'subscription': None,
        'metadata': {
            'user_id': str(user_id),
            'product_type': 'credit_pack',
            'pack_size': str(pack_size),
        },
    }


# ---------------------------------------------------------------------------
# Tests — new subscriber gets correct credits
# ---------------------------------------------------------------------------

class TestNewSubscriberCredits:
    """A user with no existing subscription gets tier.monthly_credits on checkout."""

    @pytest.mark.parametrize('tier_name,expected_credits', [
        ('starter',      200),
        ('professional', 2000),
        ('business',     10000),
    ])
    def test_new_subscriber_receives_correct_credits(
        self, app, db_session, tier_name, expected_credits
    ):
        from models import db, UserSubscription
        from routes.billing import handle_checkout_completed

        with app.app_context():
            tier = _make_tier(db, tier_name, expected_credits)
            user = _make_user(db, f'new_{tier_name}@example.com')

            # Ensure no pre-existing subscription
            UserSubscription.query.filter_by(user_id=user.id).delete()
            db.session.commit()

            handle_checkout_completed(_checkout_session(user.id, tier_name))

            sub = UserSubscription.query.filter_by(user_id=user.id).first()
            assert sub is not None, "Subscription row was not created"
            assert sub.credits_remaining == expected_credits, (
                f"{tier_name}: expected {expected_credits} credits, got {sub.credits_remaining}"
            )
            assert sub.tier_id == tier.id
            assert sub.payment_status == 'active'
            assert sub.stripe_customer_id == 'cus_test123'

            # Cleanup
            db.session.delete(sub)
            db.session.commit()


# ---------------------------------------------------------------------------
# Tests — upgrade resets credits to new tier's allowance
# ---------------------------------------------------------------------------

class TestUpgradeCredits:
    """Upgrading from a lower tier replaces credits_remaining with the new tier's monthly_credits."""

    def test_upgrade_starter_to_professional(self, app, db_session):
        from models import db, UserSubscription
        from routes.billing import handle_checkout_completed

        with app.app_context():
            starter = _make_tier(db, 'starter', 200)
            professional = _make_tier(db, 'professional', 2000)
            user = _make_user(db, 'upgrade_test@example.com')

            # Start on starter
            UserSubscription.query.filter_by(user_id=user.id).delete()
            db.session.commit()
            sub = UserSubscription(
                user_id=user.id,
                tier_id=starter.id,
                credits_remaining=50,   # partially consumed
                payment_status='active',
            )
            db.session.add(sub)
            db.session.commit()

            # Upgrade via webhook
            handle_checkout_completed(_checkout_session(user.id, 'professional'))

            db.session.refresh(sub)
            assert sub.tier_id == professional.id
            assert sub.credits_remaining == 2000
            assert sub.credits_used_this_month == 0

            # Cleanup
            db.session.delete(sub)
            db.session.commit()

    def test_upgrade_does_not_stack_credits(self, app, db_session):
        """Credits are replaced, not added on top of existing balance."""
        from models import db, UserSubscription
        from routes.billing import handle_checkout_completed

        with app.app_context():
            starter = _make_tier(db, 'starter', 200)
            professional = _make_tier(db, 'professional', 2000)
            user = _make_user(db, 'no_stack_test@example.com')

            UserSubscription.query.filter_by(user_id=user.id).delete()
            db.session.commit()
            sub = UserSubscription(
                user_id=user.id,
                tier_id=starter.id,
                credits_remaining=200,  # full balance
                payment_status='active',
            )
            db.session.add(sub)
            db.session.commit()

            handle_checkout_completed(_checkout_session(user.id, 'professional'))

            db.session.refresh(sub)
            assert sub.credits_remaining == 2000, (
                f"Credits should be exactly 2000, not 200+2000={sub.credits_remaining}"
            )

            db.session.delete(sub)
            db.session.commit()


# ---------------------------------------------------------------------------
# Tests — credit pack purchase
# ---------------------------------------------------------------------------

class TestCreditPackPurchase:
    """Buying a credit pack adds the pack_size to credits_remaining."""

    @pytest.mark.parametrize('pack_size', [100, 250, 500, 1000])
    def test_credit_pack_adds_correct_amount(self, app, db_session, pack_size):
        from models import db, UserSubscription
        from routes.billing import handle_checkout_completed

        with app.app_context():
            starter = _make_tier(db, 'starter', 200)
            user = _make_user(db, f'pack_{pack_size}@example.com')

            UserSubscription.query.filter_by(user_id=user.id).delete()
            db.session.commit()
            sub = UserSubscription(
                user_id=user.id,
                tier_id=starter.id,
                credits_remaining=50,
                payment_status='active',
            )
            db.session.add(sub)
            db.session.commit()

            handle_checkout_completed(_credit_pack_session(user.id, pack_size))

            db.session.refresh(sub)
            assert sub.credits_remaining == 50 + pack_size, (
                f"Pack {pack_size}: expected {50 + pack_size}, got {sub.credits_remaining}"
            )

            db.session.delete(sub)
            db.session.commit()


# ---------------------------------------------------------------------------
# Tests — idempotency (duplicate webhook must not double-grant)
# ---------------------------------------------------------------------------

class TestWebhookIdempotency:
    """The same Stripe event ID processed twice must not grant credits twice."""

    def test_duplicate_webhook_does_not_double_grant(self, app, db_session):
        from models import db, UserSubscription, PaymentWebhookEvent
        from routes.billing import STRIPE_ENABLED
        if not STRIPE_ENABLED:
            pytest.skip('Stripe not installed')

        from unittest.mock import patch
        import json

        with app.app_context():
            starter = _make_tier(db, 'starter', 200)
            user = _make_user(db, 'idempotent_test@example.com')

            UserSubscription.query.filter_by(user_id=user.id).delete()
            db.session.commit()

            event_id = 'evt_idempotency_test_001'
            fake_event = {
                'id': event_id,
                'type': 'checkout.session.completed',
                'data': {'object': _checkout_session(user.id, 'starter')},
            }

            # Pre-seed the idempotency record (simulates first delivery already processed)
            existing = PaymentWebhookEvent.query.get(f'stripe:{event_id}')
            if not existing:
                existing = PaymentWebhookEvent(
                    id=f'stripe:{event_id}',
                    gateway='stripe',
                    event_type='checkout.session.completed',
                )
                db.session.add(existing)
                db.session.commit()

            client = app.test_client()
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
            rec = PaymentWebhookEvent.query.get(f'stripe:{event_id}')
            if rec:
                db.session.delete(rec)
                db.session.commit()


# ---------------------------------------------------------------------------
# Tests — error paths (no silent failures)
# ---------------------------------------------------------------------------

class TestCheckoutErrorPaths:
    """handle_checkout_completed must handle bad data gracefully without crashing."""

    def test_unknown_user_id_does_not_crash(self, app, db_session):
        from routes.billing import handle_checkout_completed
        # Should log and return, not raise
        handle_checkout_completed({
            'customer': None,
            'customer_email': None,
            'metadata': {'user_id': '99999999', 'product_type': 'subscription', 'tier_name': 'starter'},
        })

    def test_unknown_tier_does_not_crash(self, app, db_session):
        from models import db
        from routes.billing import handle_checkout_completed

        with app.app_context():
            user = _make_user(db, 'bad_tier_test@example.com')
            handle_checkout_completed({
                'customer': 'cus_test',
                'customer_email': None,
                'metadata': {
                    'user_id': str(user.id),
                    'product_type': 'subscription',
                    'tier_name': 'nonexistent_tier_xyz',
                },
            })
            # No subscription should have been created
            from models import UserSubscription
            sub = UserSubscription.query.filter_by(user_id=user.id).first()
            assert sub is None

    def test_user_lookup_falls_back_to_email(self, app, db_session):
        """When user_id is absent from metadata, lookup by customer_email still works."""
        from models import db, UserSubscription
        from routes.billing import handle_checkout_completed

        with app.app_context():
            starter = _make_tier(db, 'starter', 200)
            user = _make_user(db, 'email_fallback@example.com')

            UserSubscription.query.filter_by(user_id=user.id).delete()
            db.session.commit()

            handle_checkout_completed({
                'customer': 'cus_email_fallback',
                'customer_email': user.email,
                'subscription': 'sub_email_fallback',
                'metadata': {
                    'product_type': 'subscription',
                    'tier_name': 'starter',
                    # no user_id
                },
            })

            sub = UserSubscription.query.filter_by(user_id=user.id).first()
            assert sub is not None
            assert sub.credits_remaining == 200

            db.session.delete(sub)
            db.session.commit()
