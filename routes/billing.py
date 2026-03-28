"""
Billing, subscription, credits, and Stripe webhook routes.
"""
import os
from datetime import datetime

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, g
from flask_login import login_required, current_user

from extensions import limiter
from models import (
    db, User, UserSubscription, SubscriptionTier, UserPreferences,
    CreditPurchase, UsageLog, NGNPriceConfig, PaymentWebhookEvent
)
from src.utils import get_logger

try:
    import stripe
    from stripe_integration import (
        StripePaymentService,
        create_subscription_checkout,
        create_credit_pack_checkout,
        STRIPE_PRICES,
    )
    STRIPE_ENABLED = True
except ImportError:
    STRIPE_ENABLED = False

logger = get_logger(__name__)

billing_bp = Blueprint('billing', __name__)


# ==================== HELPERS ====================


def _get_active_tiers():
    """Get active subscription tiers, cached per-request in Flask g."""
    if not hasattr(g, '_cached_tiers'):
        g._cached_tiers = SubscriptionTier.query.filter_by(is_active=True).all()
    return g._cached_tiers


def _get_ngn_prices():
    """Get NGN price config dict {product_key: price_ngn}, cached per-request in Flask g."""
    if not hasattr(g, '_cached_ngn'):
        g._cached_ngn = {p.product_key: p.price_ngn for p in NGNPriceConfig.query.filter_by(is_active=True).all()}
    return g._cached_ngn


def _get_pack_configs():
    """Get credit pack config dict {product_key: NGNPriceConfig}, cached per-request in Flask g."""
    if not hasattr(g, '_cached_pack_configs'):
        rows = NGNPriceConfig.query.filter_by(product_type='credit_pack', is_active=True).all()
        g._cached_pack_configs = {r.product_key: r for r in rows}
    return g._cached_pack_configs


def _get_ngn_price_id(product_key: str, product_type: str):
    """Return the NGN Stripe price ID for a product, or None if not configured."""
    config = NGNPriceConfig.query.filter_by(
        product_key=product_key, product_type=product_type, is_active=True
    ).first()
    if config and config.stripe_price_id_ngn:
        return config.stripe_price_id_ngn
    return None


def _ensure_subscription(
    user_id: int,
    initial_credits: int = None,
    stripe_customer_id: str = None,
    payment_gateway: str = None,
) -> 'UserSubscription | None':
    """Get-or-create a free-tier subscription for a user. Does not commit.

    Returns the existing subscription if found, otherwise creates and adds
    a free-tier one. Pass initial_credits to override the tier's monthly_credits
    (e.g. when seeding from a credit pack purchase).
    """
    from dateutil.relativedelta import relativedelta

    subscription = UserSubscription.query.filter_by(user_id=user_id).first()
    if subscription:
        return subscription

    free_tier = SubscriptionTier.query.filter_by(name='free').first()
    if not free_tier:
        return None

    now = datetime.utcnow()
    credits = initial_credits if initial_credits is not None else free_tier.monthly_credits
    subscription = UserSubscription(
        user_id=user_id,
        tier_id=free_tier.id,
        credits_remaining=credits,
        current_period_start=now,
        current_period_end=now + relativedelta(months=1),
        last_reset_date=now,
    )
    if stripe_customer_id:
        subscription.stripe_customer_id = stripe_customer_id
    if payment_gateway:
        subscription.payment_gateway = payment_gateway
    db.session.add(subscription)
    return subscription


# ==================== PAGE ROUTES ====================


@billing_bp.route('/billing')
@login_required
def billing():
    """Billing and credits management page."""
    subscription = _ensure_subscription(current_user.id)
    db.session.commit()
    if subscription and subscription.should_reset_credits():
        subscription.reset_monthly_credits()
    tiers = _get_active_tiers()
    stripe_pub_key = os.getenv('STRIPE_PUBLISHABLE_KEY', '')

    # NGN pricing support
    from services.currency_detection import detect_user_currency
    user_prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
    detected_currency = detect_user_currency(request, user_prefs)
    ngn_prices = _get_ngn_prices()
    ngn_defaults = {'starter': 15000, 'professional': 45000, 'business': 120000,
                    'pack_100': 5000, 'pack_250': 9000, 'pack_500': 15000, 'pack_1000': 25000}
    for _k, _v in ngn_defaults.items():
        ngn_prices.setdefault(_k, _v)

    return render_template(
        'billing.html',
        user=current_user,
        subscription=subscription,
        tiers=tiers,
        stripe_enabled=STRIPE_ENABLED,
        stripe_publishable_key=stripe_pub_key,
        detected_currency=detected_currency,
        ngn_prices=ngn_prices,
    )


@billing_bp.route('/billing/success')
@login_required
def billing_success():
    """Success page after Stripe checkout."""
    session_id = request.args.get('session_id')

    if session_id and STRIPE_ENABLED:
        result = StripePaymentService.retrieve_session(session_id)
        if result['success']:
            session_obj = result['session']
            # If webhook hasn't fired yet, process it now as a safety net
            metadata = session_obj.get('metadata', {})
            product_type = metadata.get('product_type')
            payment_status = session_obj.get('payment_status', '')
            if payment_status == 'paid' or session_obj.get('status') == 'complete':
                user_sub = UserSubscription.query.filter_by(user_id=current_user.id).first()
                if product_type == 'subscription':
                    tier_name = metadata.get('tier_name')
                    expected_tier = SubscriptionTier.query.filter_by(name=tier_name).first()
                    # Check if webhook already processed this
                    if not user_sub or (expected_tier and user_sub.tier_id != expected_tier.id):
                        logger.info(f"Processing checkout inline (webhook may not have fired yet) for user {current_user.id}")
                        handle_checkout_completed(session_obj)
                elif product_type == 'credit_pack':
                    # For credit packs, check if payment_intent already recorded
                    payment_intent = session_obj.get('payment_intent')
                    existing = CreditPurchase.query.filter_by(
                        stripe_payment_intent_id=payment_intent
                    ).first() if payment_intent else None
                    if not existing:
                        logger.info(f"Processing credit pack inline for user {current_user.id}")
                        handle_checkout_completed(session_obj)

    return redirect(url_for('.billing') + '?success=true')


# ==================== SUBSCRIPTION API ====================


@billing_bp.route('/api/subscription', methods=['GET'])
@login_required
def get_subscription():
    """Get current user's subscription details."""
    try:
        subscription = UserSubscription.query.filter_by(user_id=current_user.id).first()

        if not subscription:
            # Return free tier info if no subscription
            free_tier = SubscriptionTier.query.filter_by(name='free').first()
            return jsonify({
                'subscription': None,
                'available_tiers': [t.to_dict() for t in _get_active_tiers()],
                'suggested_tier': free_tier.to_dict() if free_tier else None
            })

        # Check if credits need reset
        if subscription.should_reset_credits():
            subscription.reset_monthly_credits()

        return jsonify({
            'subscription': subscription.to_dict(),
            'available_tiers': [t.to_dict() for t in _get_active_tiers()]
        })

    except Exception as e:
        logger.error(f"Error retrieving subscription: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@billing_bp.route('/api/subscription/tiers', methods=['GET'])
def get_subscription_tiers():
    """Get all available subscription tiers (public endpoint)."""
    try:
        tiers = _get_active_tiers()
        return jsonify({
            'tiers': [tier.to_dict() for tier in tiers]
        })
    except Exception as e:
        logger.error(f"Error retrieving tiers: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@billing_bp.route('/api/subscription/upgrade', methods=['POST'])
@login_required
def upgrade_subscription():
    """Upgrade user's subscription tier. Requires Stripe payment."""
    return jsonify({
        'error': 'Direct subscription upgrade is disabled. Please use the billing page to subscribe via Stripe checkout.'
    }), 403


@billing_bp.route('/api/subscription/create-checkout', methods=['POST'])
@login_required
def create_subscription_checkout_session():
    """Create Stripe checkout session for subscription upgrade."""
    if not STRIPE_ENABLED:
        logger.error("Stripe not enabled - stripe_integration import failed")
        return jsonify({'error': 'Payment processing is not enabled'}), 503

    try:
        data = request.get_json()
        tier_name = data.get('tier_name')
        currency = data.get('currency')  # 'NGN' or None/USD

        if not tier_name:
            return jsonify({'error': 'Tier name is required'}), 400

        # Debug: log Stripe config state
        api_key = stripe.api_key
        logger.info(f"Stripe checkout: tier={tier_name}, currency={currency}, api_key_set={bool(api_key)}, api_key_prefix={api_key[:12] + '...' if api_key else 'None'}")

        # NGN currency: look up NGN Stripe price ID, fall back to USD if not configured
        ngn_price_id = None
        if currency and currency.upper() == 'NGN':
            ngn_price_id = _get_ngn_price_id(tier_name.lower(), 'subscription')
            if not ngn_price_id:
                logger.info(f"NGN Stripe price not configured for {tier_name}, falling back to USD")
                currency = None

        if not ngn_price_id:
            price_id = STRIPE_PRICES['subscriptions'].get(tier_name.lower())
            logger.info(f"Stripe price_id for {tier_name}: {price_id}")
            if not price_id:
                logger.error(f"No Stripe price ID found for tier '{tier_name}'. Available: {list(STRIPE_PRICES['subscriptions'].keys())} -> {list(STRIPE_PRICES['subscriptions'].values())}")
                return jsonify({'error': f'Payments are not yet configured. Please contact support or set STRIPE_PRICE_{tier_name.upper()} in your environment.'}), 400

        result = create_subscription_checkout(
            current_user, tier_name,
            currency=currency.lower() if currency else None,
            ngn_price_id=ngn_price_id,
        )

        if result['success']:
            logger.info(f"Checkout session created: {result['session_id']}")
            return jsonify({
                'success': True,
                'checkout_url': result['checkout_url'],
                'session_id': result['session_id']
            })
        else:
            logger.error(f"Checkout creation failed: {result.get('error')}")
            return jsonify({'error': result.get('error', 'Failed to create checkout')}), 500

    except Exception as e:
        logger.error(f"Error creating checkout: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# ==================== CREDITS API ====================


@billing_bp.route('/api/credits/purchase', methods=['POST'])
@login_required
def purchase_credits():
    """Purchase additional credit packs. Requires Stripe payment."""
    return jsonify({
        'error': 'Direct credit purchase is disabled. Please use the billing page to purchase via Stripe checkout.'
    }), 403


@billing_bp.route('/api/credits/create-checkout', methods=['POST'])
@login_required
def create_credits_checkout_session():
    """Create Stripe checkout session for credit pack purchase."""
    if not STRIPE_ENABLED:
        return jsonify({'error': 'Payment processing is not enabled'}), 503

    try:
        data = request.get_json()
        pack_size = data.get('pack_size', 100)
        currency = data.get('currency')  # 'NGN' or None/USD

        if pack_size not in [100, 250, 500, 1000]:
            return jsonify({'error': 'Invalid pack size'}), 400

        # NGN currency: look up NGN Stripe price ID, fall back to USD if not configured
        ngn_price_id = None
        if currency and currency.upper() == 'NGN':
            ngn_price_id = _get_ngn_price_id(f'pack_{pack_size}', 'credit_pack')
            if not ngn_price_id:
                logger.info(f"NGN Stripe price not configured for pack_{pack_size}, falling back to USD")
                currency = None

        result = create_credit_pack_checkout(
            current_user, pack_size,
            currency=currency.lower() if currency else None,
            ngn_price_id=ngn_price_id,
        )

        if result['success']:
            logger.info(f"Credit pack checkout created: pack={pack_size}, session={result['session_id']}")
            return jsonify({
                'success': True,
                'checkout_url': result['checkout_url'],
                'session_id': result['session_id']
            })
        else:
            logger.error(f"Credit pack checkout failed: {result.get('error')}")
            return jsonify({'error': result.get('error', 'Failed to create checkout')}), 500

    except Exception as e:
        logger.error(f"Error creating checkout: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@billing_bp.route('/api/credits/packs', methods=['GET'])
def get_credit_packs():
    """Get available credit pack options (public endpoint)."""
    configs = _get_pack_configs()
    # Fallback prices match Stripe configuration — used when DB row has no price_usd yet
    _USD_FALLBACK = {'pack_100': 10.0, 'pack_250': 20.0, 'pack_500': 35.0, 'pack_1000': 60.0}
    _PACKS = [('pack_100', 100, False), ('pack_250', 250, True), ('pack_500', 500, False), ('pack_1000', 1000, False)]
    credit_packs = []
    for key, size, popular in _PACKS:
        cfg = configs.get(key)
        price = float(cfg.price_usd) if (cfg and cfg.price_usd is not None) else _USD_FALLBACK[key]
        credit_packs.append({
            'credits': size,
            'price': price,
            'price_per_credit': round(price / size, 4),
            'popular': popular,
        })
    return jsonify({'packs': credit_packs})


# ==================== BILLING INFO API ====================


@billing_bp.route('/api/billing/currency', methods=['POST'])
@login_required
def set_billing_currency():
    """Save user's preferred billing currency."""
    data = request.get_json()
    currency = data.get('currency')
    if currency not in ('USD', 'NGN', None):
        return jsonify({'error': 'Invalid currency. Must be USD, NGN, or null (auto-detect)'}), 400

    prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
    if not prefs:
        prefs = UserPreferences(user_id=current_user.id)
        db.session.add(prefs)
    prefs.preferred_currency = currency
    db.session.commit()
    return jsonify({'success': True, 'currency': currency})


@billing_bp.route('/api/billing/prices', methods=['GET'])
@login_required
def get_billing_prices():
    """Return all prices in both USD and NGN."""
    tiers = _get_active_tiers()
    ngn_configs = {p.product_key: p.to_dict() for p in NGNPriceConfig.query.filter_by(is_active=True).all()}

    subscriptions = []
    for tier in tiers:
        ngn = ngn_configs.get(tier.name, {})
        subscriptions.append({
            'name': tier.name,
            'display_name': tier.display_name,
            'price_usd': tier.monthly_price,
            'price_ngn': ngn.get('price_ngn'),
            'monthly_credits': tier.monthly_credits,
        })

    pack_configs = _get_pack_configs()
    _USD_FALLBACK = {'pack_100': 10, 'pack_250': 20, 'pack_500': 35, 'pack_1000': 60}
    credit_packs = []
    for key, size in [('pack_100', 100), ('pack_250', 250), ('pack_500', 500), ('pack_1000', 1000)]:
        cfg = pack_configs.get(key)
        price_usd = float(cfg.price_usd) if (cfg and cfg.price_usd is not None) else _USD_FALLBACK[key]
        credit_packs.append({
            'size': size,
            'price_usd': price_usd,
            'price_ngn': cfg.price_ngn if cfg else ngn_configs.get(key, {}).get('price_ngn'),
        })

    return jsonify({
        'subscriptions': subscriptions,
        'credit_packs': credit_packs,
    })


@billing_bp.route('/api/stripe/status', methods=['GET'])
@login_required
def stripe_status():
    """Diagnostic endpoint to check Stripe configuration (no secrets exposed)."""
    try:
        api_key = os.getenv('STRIPE_SECRET_KEY', '')
        status = {
            'stripe_enabled': STRIPE_ENABLED,
            'api_key_set': bool(api_key),
            'api_key_prefix': api_key[:7] + '...' if api_key else None,
            'webhook_secret_set': bool(os.getenv('STRIPE_WEBHOOK_SECRET')),
            'publishable_key_set': bool(os.getenv('STRIPE_PUBLISHABLE_KEY')),
            'base_url': os.getenv('BASE_URL', 'https://devopsagent.io'),
            'price_ids': {
                'starter': bool(os.getenv('STRIPE_PRICE_STARTER')),
                'professional': bool(os.getenv('STRIPE_PRICE_PROFESSIONAL')),
                'business': bool(os.getenv('STRIPE_PRICE_BUSINESS')),
                'pack_100': bool(os.getenv('STRIPE_PRICE_PACK_100')),
                'pack_250': bool(os.getenv('STRIPE_PRICE_PACK_250')),
                'pack_500': bool(os.getenv('STRIPE_PRICE_PACK_500')),
                'pack_1000': bool(os.getenv('STRIPE_PRICE_PACK_1000')),
            }
        }
        all_configured = (
            status['stripe_enabled'] and
            status['api_key_set'] and
            status['webhook_secret_set'] and
            all(status['price_ids'].values())
        )
        status['all_configured'] = all_configured
        return jsonify(status)
    except Exception as e:
        return jsonify({'error': str(e), 'endpoint': 'stripe_status'}), 500


# ==================== USAGE API ====================


@billing_bp.route('/api/usage/history', methods=['GET'])
@login_required
def get_usage_history():
    """Get user's credit usage history."""
    try:
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)

        logs = UsageLog.query.filter_by(
            user_id=current_user.id
        ).order_by(
            UsageLog.created_at.desc()
        ).limit(limit).offset(offset).all()

        total_count = UsageLog.query.filter_by(user_id=current_user.id).count()

        return jsonify({
            'logs': [log.to_dict() for log in logs],
            'total_count': total_count,
            'limit': limit,
            'offset': offset
        })

    except Exception as e:
        logger.error(f"Error retrieving usage history: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@billing_bp.route('/api/usage/stats', methods=['GET'])
@login_required
def get_usage_stats():
    """Get usage statistics for current user."""
    try:
        subscription = UserSubscription.query.filter_by(user_id=current_user.id).first()

        if not subscription:
            return jsonify({
                'credits_remaining': 0,
                'credits_used_this_month': 0,
                'total_credits_used': 0,
                'tier': None
            })

        from sqlalchemy import func
        from datetime import timedelta

        month_start = subscription.current_period_start or (datetime.utcnow() - timedelta(days=30))

        tool_usage = db.session.query(
            UsageLog.tool_name,
            func.count(UsageLog.id).label('count')
        ).filter(
            UsageLog.user_id == current_user.id,
            UsageLog.created_at >= month_start
        ).group_by(UsageLog.tool_name).all()

        return jsonify({
            'credits_remaining': subscription.credits_remaining,
            'credits_used_this_month': subscription.credits_used_this_month,
            'total_credits_used': subscription.total_credits_used,
            'tier': subscription.tier.to_dict() if subscription.tier else None,
            'current_period_start': subscription.current_period_start.isoformat() if subscription.current_period_start else None,
            'current_period_end': subscription.current_period_end.isoformat() if subscription.current_period_end else None,
            'tool_usage_breakdown': [{'tool': tool or 'agent_message', 'count': count} for tool, count in tool_usage]
        })

    except Exception as e:
        logger.error(f"Error retrieving usage stats: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# ==================== STRIPE WEBHOOK ====================


@billing_bp.route('/api/stripe/webhook', methods=['POST'])
@limiter.limit("200 per minute")
def stripe_webhook():
    """Handle Stripe webhook events."""
    if not STRIPE_ENABLED:
        return jsonify({'error': 'Stripe not enabled'}), 503

    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')

    try:
        event = StripePaymentService.construct_webhook_event(payload, sig_header)
    except ValueError as e:
        logger.error(f"Stripe webhook signature verification failed: {e} | sig_header={sig_header[:60] if sig_header else 'MISSING'}")
        return jsonify({'error': str(e)}), 400

    logger.info(f"Received Stripe webhook: {event['type']}")

    # Idempotency: INSERT the event key BEFORE running handlers using flush().
    # An IntegrityError on flush means the event was already processed (duplicate) —
    # return 200 immediately.  If a handler later fails and rolls back, the flush is
    # also rolled back, so Stripe can retry and we'll process it cleanly next time.
    # Because the handlers call db.session.commit() internally, the flushed event
    # record is committed atomically with the business logic — no post-handler INSERT needed.
    from sqlalchemy.exc import IntegrityError
    event_id = event.get('id')
    webhook_key = f"stripe:{event_id}" if event_id else None
    if webhook_key:
        try:
            db.session.add(PaymentWebhookEvent(id=webhook_key, gateway='stripe', event_type=event['type']))
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            logger.info(f"Duplicate webhook event {webhook_key}, skipping")
            return jsonify({'success': True, 'duplicate': True})

    # Handle different event types — handlers raise on unrecoverable errors so we
    # return 500 and Stripe retries instead of silently losing the event.
    try:
        if event['type'] == 'checkout.session.completed':
            handle_checkout_completed(event['data']['object'])

        elif event['type'] == 'invoice.payment_succeeded':
            handle_invoice_payment_succeeded(event['data']['object'])

        elif event['type'] == 'invoice.payment_failed':
            handle_invoice_payment_failed(event['data']['object'])

        elif event['type'] == 'customer.subscription.updated':
            handle_customer_subscription_updated(event['data']['object'])

        elif event['type'] == 'customer.subscription.deleted':
            handle_subscription_deleted(event['data']['object'])

    except Exception as e:
        db.session.rollback()
        logger.error(f"Webhook handler failed for {event.get('type')} ({webhook_key}): {e}", exc_info=True)
        return jsonify({'error': 'Handler failed, will retry'}), 500

    return jsonify({'success': True})


# ==================== WEBHOOK HANDLERS ====================


def handle_checkout_completed(session):
    """Handle successful checkout session."""
    try:
        customer_email = session.get('customer_email')
        metadata = session.get('metadata', {})
        product_type = metadata.get('product_type')
        stripe_customer_id = session.get('customer')

        # Find user: prefer user_id from metadata, fall back to email
        user = None
        user_id_str = metadata.get('user_id')
        if user_id_str:
            user = User.query.get(int(user_id_str))
        if not user and customer_email:
            user = User.query.filter_by(email=customer_email).first()
        if not user:
            logger.error(f"User not found for checkout session. user_id={user_id_str}, email={customer_email}")
            return

        if product_type == 'subscription':
            tier_name = metadata.get('tier_name')
            tier = SubscriptionTier.query.filter_by(name=tier_name).first()

            if not tier:
                logger.error(f"Tier '{tier_name}' not found in database")
                return

            from dateutil.relativedelta import relativedelta
            subscription = UserSubscription.query.filter_by(user_id=user.id).first()
            if subscription:
                old_credits = subscription.tier.monthly_credits if subscription.tier else 0
                subscription.tier_id = tier.id
                subscription.stripe_subscription_id = session.get('subscription')
                subscription.stripe_customer_id = stripe_customer_id
                subscription.payment_status = 'active'
                subscription.payment_gateway = 'stripe'
                subscription.payment_failed_at = None
                subscription.credits_remaining = tier.monthly_credits
                subscription.credits_used_this_month = 0
                subscription.current_period_start = datetime.utcnow()
                subscription.current_period_end = datetime.utcnow() + relativedelta(months=1)
                subscription.last_reset_date = datetime.utcnow()
            else:
                subscription = UserSubscription(
                    user_id=user.id,
                    tier_id=tier.id,
                    credits_remaining=tier.monthly_credits,
                    stripe_subscription_id=session.get('subscription'),
                    stripe_customer_id=stripe_customer_id,
                    payment_status='active',
                    payment_gateway='stripe',
                    current_period_start=datetime.utcnow(),
                    current_period_end=datetime.utcnow() + relativedelta(months=1),
                    last_reset_date=datetime.utcnow(),
                )
                db.session.add(subscription)

            try:
                db.session.commit()
            except Exception as db_err:
                db.session.rollback()
                logger.error(
                    f"DB commit failed granting subscription '{tier_name}' to user {user.id} "
                    f"after payment. Stripe will retry. Error: {db_err}",
                    exc_info=True
                )
                raise
            logger.info(f"Subscription '{tier_name}' activated for user {user.id} (customer={stripe_customer_id})")

            # Conversion funnel: upgrade_completed
            try:
                from models import ConversionEvent
                db.session.add(ConversionEvent(
                    user_id=user.id,
                    event_type='upgrade_completed',
                    event_metadata={'tier': tier_name, 'gateway': 'stripe'},
                ))
                db.session.commit()
            except Exception:
                pass

            try:
                from services.email_service import email_service
                if user.email:
                    email_service.send_subscription_confirmation(user, tier.display_name or tier_name.capitalize())
            except Exception as email_err:
                logger.warning(f"Failed to send subscription confirmation email to user {user.id}: {email_err}")

        elif product_type == 'credit_pack':
            pack_size = int(metadata.get('pack_size', 0))
            amount_paid = session.get('amount_total', 0) / 100  # Convert from cents

            purchase = CreditPurchase(
                user_id=user.id,
                credits_amount=pack_size,
                price_paid=amount_paid,
                stripe_payment_intent_id=session.get('payment_intent'),
                payment_status='completed',
                completed_at=datetime.utcnow()
            )
            db.session.add(purchase)

            subscription = UserSubscription.query.filter_by(user_id=user.id).first()
            if subscription:
                if stripe_customer_id and not subscription.stripe_customer_id:
                    subscription.stripe_customer_id = stripe_customer_id
                subscription.add_credits(pack_size)
            else:
                _ensure_subscription(
                    user.id,
                    initial_credits=pack_size,
                    stripe_customer_id=stripe_customer_id,
                    payment_gateway='stripe',
                )

            try:
                db.session.commit()
            except Exception as db_err:
                db.session.rollback()
                logger.error(
                    f"DB commit failed granting {pack_size} credits to user {user.id} "
                    f"after payment. Stripe will retry. Error: {db_err}",
                    exc_info=True
                )
                raise
            logger.info(f"Credit pack ({pack_size}) purchased for user {user.id}")

            try:
                from services.email_service import email_service
                if user.email:
                    from services.email_service import EmailService
                    html = email_service._wrap_html(f"""
                        <h2 style="color: #10b981; margin-bottom: 12px;">Credits Added</h2>
                        <p>Hi {user.username},</p>
                        <p><strong>{pack_size} credits</strong> have been added to your account.</p>
                        <div style="text-align: center; margin: 24px 0;">
                            <a href="{email_service.base_url}" style="display: inline-block; padding: 12px 32px; background: linear-gradient(135deg, #ff6b35, #f7931e); color: white; text-decoration: none; border-radius: 8px; font-weight: 600;">
                                Start Using Credits
                            </a>
                        </div>
                    """)
                    email_service.send_email(user.email, f"{pack_size} Credits Added - DevOps Agent", html)
            except Exception as email_err:
                logger.warning(f"Failed to send credit pack confirmation email to user {user.id}: {email_err}")

    except Exception as e:
        logger.error(f"Error handling checkout: {str(e)}", exc_info=True)
        db.session.rollback()


def handle_invoice_payment_succeeded(invoice):
    """Handle successful subscription invoice payment (recurring billing)."""
    try:
        customer_id = invoice.get('customer')
        subscription_id = invoice.get('subscription')
        if not customer_id and not subscription_id:
            return

        user_subscription = None
        if customer_id:
            user_subscription = UserSubscription.query.filter_by(
                stripe_customer_id=customer_id
            ).first()
        if not user_subscription and subscription_id:
            user_subscription = UserSubscription.query.filter_by(
                stripe_subscription_id=subscription_id
            ).first()

        if not user_subscription:
            logger.warning(f"No subscription found for Stripe customer={customer_id} sub={subscription_id}")
            return

        # Save customer_id if we found by subscription_id
        if customer_id and not user_subscription.stripe_customer_id:
            user_subscription.stripe_customer_id = customer_id

        from dateutil.relativedelta import relativedelta
        user_subscription.payment_status = 'active'
        user_subscription.payment_failed_at = None
        user_subscription.credits_remaining = user_subscription.tier.monthly_credits
        user_subscription.credits_used_this_month = 0
        user_subscription.last_reset_date = datetime.utcnow()
        user_subscription.current_period_start = datetime.utcnow()
        user_subscription.current_period_end = datetime.utcnow() + relativedelta(months=1)

        db.session.commit()
        logger.info(f"Recurring payment processed for user {user_subscription.user_id}")

    except Exception as e:
        logger.error(f"Error handling invoice payment: {str(e)}", exc_info=True)
        db.session.rollback()


def handle_subscription_deleted(subscription):
    """Handle subscription cancellation."""
    try:
        stripe_sub_id = subscription.get('id')
        user_subscription = UserSubscription.query.filter_by(
            stripe_subscription_id=stripe_sub_id
        ).first()

        if user_subscription:
            user_subscription.payment_status = 'cancelled'
            db.session.commit()
            logger.info(f"Subscription cancelled for user {user_subscription.user_id}")

    except Exception as e:
        logger.error(f"Error handling subscription deletion: {str(e)}", exc_info=True)
        db.session.rollback()


def handle_invoice_payment_failed(invoice):
    """Handle failed subscription invoice payment."""
    try:
        customer_id = invoice.get('customer')
        subscription_id = invoice.get('subscription')
        if not customer_id and not subscription_id:
            return

        user_subscription = None
        if customer_id:
            user_subscription = UserSubscription.query.filter_by(
                stripe_customer_id=customer_id
            ).first()
        if not user_subscription and subscription_id:
            user_subscription = UserSubscription.query.filter_by(
                stripe_subscription_id=subscription_id
            ).first()

        if not user_subscription:
            return

        user_subscription.payment_status = 'past_due'
        if not user_subscription.payment_failed_at:
            user_subscription.payment_failed_at = datetime.utcnow()

        # If past_due for > 3 days, downgrade to free tier
        if user_subscription.payment_failed_at:
            days_overdue = (datetime.utcnow() - user_subscription.payment_failed_at).days
            if days_overdue > 3:
                free_tier = SubscriptionTier.query.filter_by(name='free').first()
                if free_tier:
                    user_subscription.tier_id = free_tier.id
                    user_subscription.credits_remaining = min(
                        user_subscription.credits_remaining, free_tier.monthly_credits
                    )
                    logger.warning(f"Downgraded user {user_subscription.user_id} to free tier after {days_overdue} days overdue")

        db.session.commit()
        logger.info(f"Payment failed for user {user_subscription.user_id}")

        try:
            from services.email_service import email_service
            user = User.query.get(user_subscription.user_id)
            if user and user.email:
                email_service.send_payment_failed_warning(user)
        except Exception as email_err:
            logger.warning(f"Failed to send payment failed email: {email_err}")

    except Exception as e:
        logger.error(f"Error handling payment failure: {str(e)}", exc_info=True)
        db.session.rollback()


def handle_customer_subscription_updated(stripe_subscription):
    """Handle subscription changes (upgrades/downgrades)."""
    try:
        stripe_sub_id = stripe_subscription.get('id')
        user_subscription = UserSubscription.query.filter_by(
            stripe_subscription_id=stripe_sub_id
        ).first()

        if not user_subscription:
            return

        status = stripe_subscription.get('status', 'active')
        status_map = {
            'active': 'active',
            'past_due': 'past_due',
            'canceled': 'cancelled',
            'unpaid': 'past_due',
            'trialing': 'active',
        }
        user_subscription.payment_status = status_map.get(status, 'active')

        # Check if plan/price changed via metadata
        items = stripe_subscription.get('items', {}).get('data', [])
        if items:
            price_id = items[0].get('price', {}).get('id')
            if price_id:
                for tier_name in ['starter', 'professional', 'business']:
                    env_price = os.getenv(f'STRIPE_PRICE_{tier_name.upper()}')
                    if env_price == price_id:
                        new_tier = SubscriptionTier.query.filter_by(name=tier_name).first()
                        if new_tier and new_tier.id != user_subscription.tier_id:
                            old_tier = user_subscription.tier
                            user_subscription.tier_id = new_tier.id
                            if new_tier.monthly_credits > old_tier.monthly_credits:
                                diff = new_tier.monthly_credits - old_tier.monthly_credits
                                user_subscription.add_credits(diff)
                            logger.info(f"User {user_subscription.user_id} changed plan: {old_tier.name} -> {new_tier.name}")
                        break

        db.session.commit()

    except Exception as e:
        logger.error(f"Error handling subscription update: {str(e)}", exc_info=True)
        db.session.rollback()
