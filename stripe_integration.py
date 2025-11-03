"""
Stripe Payment Integration for DevOps Agent
Handles subscriptions and one-time credit pack purchases
"""
import os
import stripe
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv('config/.env')

# Initialize Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

# Stripe Price IDs from environment
STRIPE_PRICES = {
    'subscriptions': {
        'starter': os.getenv('STRIPE_PRICE_STARTER'),
        'professional': os.getenv('STRIPE_PRICE_PROFESSIONAL'),
        'business': os.getenv('STRIPE_PRICE_BUSINESS'),
    },
    'credit_packs': {
        100: os.getenv('STRIPE_PRICE_PACK_100'),
        250: os.getenv('STRIPE_PRICE_PACK_250'),
        500: os.getenv('STRIPE_PRICE_PACK_500'),
        1000: os.getenv('STRIPE_PRICE_PACK_1000'),
    }
}


class StripePaymentService:
    """Service for handling Stripe payments"""

    @staticmethod
    def create_checkout_session_subscription(user_email, tier_name, tier_price_id, success_url, cancel_url):
        """
        Create a Stripe Checkout session for subscription

        Args:
            user_email: User's email address
            tier_name: Name of the subscription tier (starter, professional, business)
            tier_price_id: Stripe price ID for the tier
            success_url: URL to redirect after successful payment
            cancel_url: URL to redirect if payment is cancelled

        Returns:
            dict: Session details with checkout URL
        """
        try:
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price': tier_price_id,
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=success_url + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=cancel_url,
                customer_email=user_email,
                metadata={
                    'tier_name': tier_name,
                    'product_type': 'subscription'
                }
            )

            return {
                'success': True,
                'session_id': session.id,
                'checkout_url': session.url
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def create_checkout_session_credits(user_email, pack_size, pack_price_id, success_url, cancel_url):
        """
        Create a Stripe Checkout session for one-time credit purchase

        Args:
            user_email: User's email address
            pack_size: Number of credits (100, 250, 500, 1000)
            pack_price_id: Stripe price ID for the credit pack
            success_url: URL to redirect after successful payment
            cancel_url: URL to redirect if payment is cancelled

        Returns:
            dict: Session details with checkout URL
        """
        try:
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price': pack_price_id,
                    'quantity': 1,
                }],
                mode='payment',  # One-time payment
                success_url=success_url + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=cancel_url,
                customer_email=user_email,
                metadata={
                    'pack_size': pack_size,
                    'product_type': 'credit_pack'
                }
            )

            return {
                'success': True,
                'session_id': session.id,
                'checkout_url': session.url
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def retrieve_session(session_id):
        """
        Retrieve a checkout session

        Args:
            session_id: Stripe session ID

        Returns:
            dict: Session object or error
        """
        try:
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
        """
        Create a Stripe customer

        Args:
            email: Customer email
            name: Customer name (optional)

        Returns:
            dict: Customer object or error
        """
        try:
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
        """
        Cancel a subscription

        Args:
            subscription_id: Stripe subscription ID

        Returns:
            dict: Cancellation result
        """
        try:
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
        """
        Construct and verify webhook event

        Args:
            payload: Request body
            sig_header: Stripe signature header

        Returns:
            stripe.Event: Verified event object
        """
        webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
            return event
        except ValueError:
            # Invalid payload
            raise ValueError('Invalid payload')
        except Exception:
            # Invalid signature
            raise ValueError('Invalid signature')

    @staticmethod
    def get_price_id(tier_name=None, pack_size=None):
        """
        Get Stripe price ID for a tier or credit pack

        Args:
            tier_name: Subscription tier name (starter, professional, business)
            pack_size: Credit pack size (100, 250, 500, 1000)

        Returns:
            str: Stripe price ID or None
        """
        if tier_name:
            return STRIPE_PRICES['subscriptions'].get(tier_name.lower())
        elif pack_size:
            return STRIPE_PRICES['credit_packs'].get(int(pack_size))
        return None


# Helper functions for common operations

def create_subscription_checkout(user, tier_name):
    """
    Create a subscription checkout session for a user

    Args:
        user: User model instance
        tier_name: Tier name (starter, professional, business)

    Returns:
        dict: Checkout session details
    """
    price_id = StripePaymentService.get_price_id(tier_name=tier_name)

    if not price_id:
        return {'success': False, 'error': f'Invalid tier: {tier_name}'}

    base_url = os.getenv('BASE_URL', 'http://localhost:5000')
    success_url = f'{base_url}/billing/success'
    cancel_url = f'{base_url}/billing'

    return StripePaymentService.create_checkout_session_subscription(
        user_email=user.email,
        tier_name=tier_name,
        tier_price_id=price_id,
        success_url=success_url,
        cancel_url=cancel_url
    )


def create_credit_pack_checkout(user, pack_size):
    """
    Create a credit pack checkout session for a user

    Args:
        user: User model instance
        pack_size: Number of credits (100, 250, 500, 1000)

    Returns:
        dict: Checkout session details
    """
    price_id = StripePaymentService.get_price_id(pack_size=pack_size)

    if not price_id:
        return {'success': False, 'error': f'Invalid pack size: {pack_size}'}

    base_url = os.getenv('BASE_URL', 'http://localhost:5000')
    success_url = f'{base_url}/billing/success'
    cancel_url = f'{base_url}/billing'

    return StripePaymentService.create_checkout_session_credits(
        user_email=user.email,
        pack_size=pack_size,
        pack_price_id=price_id,
        success_url=success_url,
        cancel_url=cancel_url
    )
