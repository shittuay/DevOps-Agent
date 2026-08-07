"""
Stripe Payment Integration for DevOps Agent
Handles subscriptions and one-time credit pack purchases
"""
import os
import logging
import stripe
from datetime import datetime

logger = logging.getLogger(__name__)


def _read_config_env():
    """Read config/.env directly as the local/dev FALLBACK for Stripe config.

    Precedence (changed 2026-07-17 after the key-rotation outage): os.environ
    wins, because in production init_secrets() loads AWS Secrets Manager into
    os.environ at startup — Secrets Manager is the single source of truth for
    rotations. config/.env only fills gaps (local dev without SM access)."""
    config_path = os.path.join(os.path.dirname(__file__), 'config', '.env')
    values = {}
    if os.path.exists(config_path):
        try:
            from dotenv import dotenv_values
            values = dotenv_values(config_path)
        except Exception:
            pass
    return values


def _in_production():
    return (
        os.environ.get('FLASK_ENV') == 'production'
        or os.environ.get('USE_AWS_SECRETS', '').lower() == 'true'
    )


def _ensure_stripe_configured():
    """Ensure stripe.api_key is set — env (Secrets Manager) first, then config/.env.

    In production the config/.env fallback is deliberately NOT used. That file
    can hold a pre-rotation key, and Stripe answers a revoked key with a plain
    401 'Invalid API Key' — indistinguishable, from the outside, from a key that
    expired on its own. Silently charging ahead with a stale credential turned a
    one-line rotation into a recurring outage. Fail loudly instead: a clear error
    is recoverable, a wrong key that half-works is not.
    """
    env_key = os.getenv('STRIPE_SECRET_KEY')

    if _in_production():
        from services.secrets_manager import secrets_are_authoritative, get_secrets_state
        if not secrets_are_authoritative():
            state = get_secrets_state()
            raise RuntimeError(
                'Refusing to use a possibly-stale Stripe key: secrets did not load '
                f"from AWS Secrets Manager (source={state.get('source')}, "
                f"error={state.get('error')}). Fix Secrets Manager access, then "
                'POST /admin/api/secrets/reload — no redeploy needed.'
            )
        if not env_key:
            raise RuntimeError(
                'STRIPE_SECRET_KEY missing from AWS Secrets Manager secret '
                "'devops-agent/production'."
            )
        stripe.api_key = env_key
        return

    config = _read_config_env()
    stripe.api_key = env_key or config.get('STRIPE_SECRET_KEY')
    if not stripe.api_key:
        raise RuntimeError('STRIPE_SECRET_KEY is not set (Secrets Manager or config/.env)')


def _get_subscription_prices():
    """Get subscription price IDs — env (Secrets Manager) first, then config/.env."""
    config = _read_config_env()
    return {
        'starter': os.getenv('STRIPE_PRICE_STARTER') or config.get('STRIPE_PRICE_STARTER'),
        'professional': os.getenv('STRIPE_PRICE_PROFESSIONAL') or config.get('STRIPE_PRICE_PROFESSIONAL'),
        'business': os.getenv('STRIPE_PRICE_BUSINESS') or config.get('STRIPE_PRICE_BUSINESS'),
    }


def _get_credit_pack_prices():
    """Get credit pack price IDs — env (Secrets Manager) first, then config/.env."""
    config = _read_config_env()
    return {
        100: os.getenv('STRIPE_PRICE_PACK_100') or config.get('STRIPE_PRICE_PACK_100'),
        250: os.getenv('STRIPE_PRICE_PACK_250') or config.get('STRIPE_PRICE_PACK_250'),
        500: os.getenv('STRIPE_PRICE_PACK_500') or config.get('STRIPE_PRICE_PACK_500'),
        1000: os.getenv('STRIPE_PRICE_PACK_1000') or config.get('STRIPE_PRICE_PACK_1000'),
    }


# Keep STRIPE_PRICES as a property-like accessor for backward compat with app.py debug logging
class _StripePricesAccessor:
    @property
    def data(self):
        return {
            'subscriptions': _get_subscription_prices(),
            'credit_packs': _get_credit_pack_prices(),
        }

    def __getitem__(self, key):
        return self.data[key]

STRIPE_PRICES = _StripePricesAccessor()


class StripePaymentService:
    """Service for handling Stripe payments"""

    @staticmethod
    def create_checkout_session_subscription(user_email, tier_name, tier_price_id, success_url, cancel_url, currency=None, user_id=None):
        """Create a Stripe Checkout session for subscription.

        Args:
            currency: Optional currency code (e.g. 'ngn'). If set, Stripe creates
                      the checkout page in that currency.
            user_id: Internal user ID stored in metadata for reliable webhook lookup.
        """
        try:
            _ensure_stripe_configured()
            metadata = {
                'tier_name': tier_name,
                'product_type': 'subscription',
                'currency': currency or 'usd',
            }
            if user_id:
                metadata['user_id'] = str(user_id)
            session_params = dict(
                payment_method_types=['card'],
                line_items=[{
                    'price': tier_price_id,
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=success_url + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=cancel_url,
                customer_email=user_email,
                metadata=metadata,
                subscription_data={'metadata': metadata},
            )
            if currency:
                session_params['currency'] = currency.lower()
            session = stripe.checkout.Session.create(**session_params)

            return {
                'success': True,
                'session_id': session.id,
                'checkout_url': session.url
            }

        except Exception as e:
            logger.error(f"Stripe checkout session error: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def create_checkout_session_credits(user_email, pack_size, pack_price_id, success_url, cancel_url, currency=None, user_id=None):
        """Create a Stripe Checkout session for one-time credit purchase.

        Args:
            currency: Optional currency code (e.g. 'ngn'). If set, Stripe creates
                      the checkout page in that currency.
            user_id: Internal user ID stored in metadata for reliable webhook lookup.
        """
        try:
            _ensure_stripe_configured()
            metadata = {
                'pack_size': pack_size,
                'product_type': 'credit_pack',
                'currency': currency or 'usd',
            }
            if user_id:
                metadata['user_id'] = str(user_id)
            session_params = dict(
                payment_method_types=['card'],
                line_items=[{
                    'price': pack_price_id,
                    'quantity': 1,
                }],
                mode='payment',
                success_url=success_url + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=cancel_url,
                customer_email=user_email,
                metadata=metadata,
            )
            if currency:
                session_params['currency'] = currency.lower()
            session = stripe.checkout.Session.create(**session_params)

            return {
                'success': True,
                'session_id': session.id,
                'checkout_url': session.url
            }

        except Exception as e:
            logger.error(f"Stripe credit checkout error: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def retrieve_session(session_id):
        """Retrieve a checkout session."""
        try:
            _ensure_stripe_configured()
            session = stripe.checkout.Session.retrieve(session_id)
            return {
                'success': True,
                'session': session
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def create_customer(email, name=None):
        """Create a Stripe customer."""
        try:
            _ensure_stripe_configured()
            customer = stripe.Customer.create(
                email=email,
                name=name
            )
            return {
                'success': True,
                'customer_id': customer.id
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def cancel_subscription(subscription_id):
        """Cancel a subscription."""
        try:
            _ensure_stripe_configured()
            subscription = stripe.Subscription.delete(subscription_id)
            return {
                'success': True,
                'subscription': subscription
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def construct_webhook_event(payload, sig_header):
        """Construct and verify webhook event."""
        webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')
        if not webhook_secret:
            raise ValueError('STRIPE_WEBHOOK_SECRET is not set')

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
            return event
        except ValueError:
            raise ValueError('Invalid payload')
        except Exception:
            raise ValueError('Invalid signature')

    @staticmethod
    def get_price_id(tier_name=None, pack_size=None):
        """Get Stripe price ID for a tier or credit pack (reads env at call time)."""
        if tier_name:
            prices = _get_subscription_prices()
            price_id = prices.get(tier_name.lower())
            if not price_id:
                logger.warning(f"No price ID for tier '{tier_name}'. Env values: {prices}")
            return price_id
        elif pack_size:
            prices = _get_credit_pack_prices()
            price_id = prices.get(int(pack_size))
            if not price_id:
                logger.warning(f"No price ID for pack size {pack_size}. Env values: {prices}")
            return price_id
        return None


# Helper functions for common operations

def create_subscription_checkout(user, tier_name, currency=None, ngn_price_id=None):
    """Create a subscription checkout session for a user.

    Args:
        currency: 'ngn' to create a Naira checkout, None/usd for dollars.
        ngn_price_id: Stripe Price ID for the NGN product (from NGNPriceConfig.stripe_price_id_ngn).
    """
    if currency and currency.lower() == 'ngn' and ngn_price_id:
        price_id = ngn_price_id
    else:
        price_id = StripePaymentService.get_price_id(tier_name=tier_name)
        currency = None  # USD is Stripe default

    if not price_id:
        return {'success': False, 'error': f'Stripe price not configured for tier: {tier_name}. Check STRIPE_PRICE_{tier_name.upper()} env var.'}

    base_url = os.getenv('BASE_URL', 'https://devopsagent.io')
    success_url = f'{base_url}/billing/success'
    cancel_url = f'{base_url}/billing'

    return StripePaymentService.create_checkout_session_subscription(
        user_email=user.email,
        tier_name=tier_name,
        tier_price_id=price_id,
        success_url=success_url,
        cancel_url=cancel_url,
        currency=currency,
        user_id=user.id,
    )


def create_credit_pack_checkout(user, pack_size, currency=None, ngn_price_id=None):
    """Create a credit pack checkout session for a user.

    Args:
        currency: 'ngn' to create a Naira checkout, None/usd for dollars.
        ngn_price_id: Stripe Price ID for the NGN product (from NGNPriceConfig.stripe_price_id_ngn).
    """
    if currency and currency.lower() == 'ngn' and ngn_price_id:
        price_id = ngn_price_id
    else:
        price_id = StripePaymentService.get_price_id(pack_size=pack_size)
        currency = None

    if not price_id:
        return {'success': False, 'error': f'Stripe price not configured for pack size: {pack_size}. Check STRIPE_PRICE_PACK_{pack_size} env var.'}

    base_url = os.getenv('BASE_URL', 'https://devopsagent.io')
    success_url = f'{base_url}/billing/success'
    cancel_url = f'{base_url}/billing'

    return StripePaymentService.create_checkout_session_credits(
        user_email=user.email,
        pack_size=pack_size,
        pack_price_id=price_id,
        success_url=success_url,
        cancel_url=cancel_url,
        currency=currency,
        user_id=user.id,
    )
