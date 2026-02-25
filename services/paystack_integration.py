"""
Paystack Payment Integration for DevOps Agent
Handles Nigerian Naira (NGN) subscriptions and one-time credit pack purchases via Paystack.
"""
import os
import hmac
import hashlib
import logging
import uuid
import requests
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

PAYSTACK_BASE_URL = 'https://api.paystack.co'


def _get_secret_key() -> str:
    key = os.getenv('PAYSTACK_SECRET_KEY')
    if not key:
        raise RuntimeError('PAYSTACK_SECRET_KEY is not set in environment')
    return key


def _headers() -> Dict[str, str]:
    return {
        'Authorization': f'Bearer {_get_secret_key()}',
        'Content-Type': 'application/json',
    }


def _generate_reference() -> str:
    return f'da-ps-{uuid.uuid4().hex[:12]}'


class PaystackPaymentService:
    """Service for handling Paystack payments (NGN)."""

    @staticmethod
    def initialize_transaction(
        email: str,
        amount_naira: int,
        callback_url: str,
        metadata: Optional[Dict[str, Any]] = None,
        reference: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Initialize a Paystack transaction.

        Args:
            email: Customer email
            amount_naira: Amount in whole naira (converted to kobo internally)
            callback_url: URL to redirect after payment
            metadata: Additional metadata (product_type, tier_name, etc.)
            reference: Optional payment reference (auto-generated if not provided)
        """
        try:
            ref = reference or _generate_reference()
            payload = {
                'email': email,
                'amount': amount_naira * 100,  # Convert naira to kobo
                'currency': 'NGN',
                'reference': ref,
                'callback_url': callback_url,
                'metadata': metadata or {},
            }

            resp = requests.post(
                f'{PAYSTACK_BASE_URL}/transaction/initialize',
                json=payload,
                headers=_headers(),
                timeout=30,
            )
            data = resp.json()

            if data.get('status'):
                return {
                    'success': True,
                    'authorization_url': data['data']['authorization_url'],
                    'access_code': data['data']['access_code'],
                    'reference': data['data']['reference'],
                }
            else:
                logger.error(f"Paystack init failed: {data.get('message')}")
                return {'success': False, 'error': data.get('message', 'Transaction initialization failed')}

        except Exception as e:
            logger.error(f"Paystack initialize_transaction error: {e}")
            return {'success': False, 'error': str(e)}

    @staticmethod
    def verify_transaction(reference: str) -> Dict[str, Any]:
        """Verify a Paystack transaction by reference."""
        try:
            resp = requests.get(
                f'{PAYSTACK_BASE_URL}/transaction/verify/{reference}',
                headers=_headers(),
                timeout=30,
            )
            data = resp.json()

            if data.get('status') and data['data'].get('status') == 'success':
                txn = data['data']
                return {
                    'success': True,
                    'amount_kobo': txn['amount'],
                    'amount_naira': txn['amount'] // 100,
                    'currency': txn['currency'],
                    'reference': txn['reference'],
                    'customer_email': txn['customer']['email'],
                    'customer_code': txn['customer']['customer_code'],
                    'metadata': txn.get('metadata', {}),
                    'paid_at': txn.get('paid_at'),
                }
            else:
                status = data.get('data', {}).get('status', 'unknown')
                return {'success': False, 'error': f'Transaction not successful (status: {status})'}

        except Exception as e:
            logger.error(f"Paystack verify_transaction error: {e}")
            return {'success': False, 'error': str(e)}

    @staticmethod
    def create_plan(name: str, amount_naira: int, interval: str = 'monthly') -> Dict[str, Any]:
        """
        Create a subscription plan on Paystack.

        Args:
            name: Plan name
            amount_naira: Amount in whole naira
            interval: 'monthly', 'yearly', 'weekly', etc.
        """
        try:
            payload = {
                'name': name,
                'amount': amount_naira * 100,  # kobo
                'interval': interval,
                'currency': 'NGN',
            }

            resp = requests.post(
                f'{PAYSTACK_BASE_URL}/plan',
                json=payload,
                headers=_headers(),
                timeout=30,
            )
            data = resp.json()

            if data.get('status'):
                return {
                    'success': True,
                    'plan_code': data['data']['plan_code'],
                    'plan_id': data['data']['id'],
                }
            else:
                return {'success': False, 'error': data.get('message', 'Plan creation failed')}

        except Exception as e:
            logger.error(f"Paystack create_plan error: {e}")
            return {'success': False, 'error': str(e)}

    @staticmethod
    def create_subscription(customer_code: str, plan_code: str) -> Dict[str, Any]:
        """Create a subscription for an existing customer."""
        try:
            payload = {
                'customer': customer_code,
                'plan': plan_code,
            }

            resp = requests.post(
                f'{PAYSTACK_BASE_URL}/subscription',
                json=payload,
                headers=_headers(),
                timeout=30,
            )
            data = resp.json()

            if data.get('status'):
                return {
                    'success': True,
                    'subscription_code': data['data']['subscription_code'],
                    'email_token': data['data']['email_token'],
                }
            else:
                return {'success': False, 'error': data.get('message', 'Subscription creation failed')}

        except Exception as e:
            logger.error(f"Paystack create_subscription error: {e}")
            return {'success': False, 'error': str(e)}

    @staticmethod
    def cancel_subscription(subscription_code: str, email_token: str) -> Dict[str, Any]:
        """Cancel a Paystack subscription."""
        try:
            payload = {
                'code': subscription_code,
                'token': email_token,
            }

            resp = requests.post(
                f'{PAYSTACK_BASE_URL}/subscription/disable',
                json=payload,
                headers=_headers(),
                timeout=30,
            )
            data = resp.json()

            if data.get('status'):
                return {'success': True}
            else:
                return {'success': False, 'error': data.get('message', 'Cancellation failed')}

        except Exception as e:
            logger.error(f"Paystack cancel_subscription error: {e}")
            return {'success': False, 'error': str(e)}

    @staticmethod
    def verify_webhook_signature(payload: bytes, signature: str) -> bool:
        """Verify Paystack webhook signature using HMAC SHA512."""
        secret = _get_secret_key()
        expected = hmac.new(
            secret.encode('utf-8'),
            msg=payload,
            digestmod=hashlib.sha512,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


# Helper functions matching stripe_integration.py pattern

def create_paystack_subscription_checkout(user, tier_name: str, plan_code: str, amount_naira: int) -> Dict[str, Any]:
    """Create a Paystack checkout for subscription."""
    base_url = os.getenv('BASE_URL', 'https://devopsagent.io')
    callback_url = f'{base_url}/billing/success?gateway=paystack'

    return PaystackPaymentService.initialize_transaction(
        email=user.email,
        amount_naira=amount_naira,
        callback_url=callback_url,
        metadata={
            'product_type': 'subscription',
            'tier_name': tier_name,
            'plan_code': plan_code,
            'user_id': user.id,
        },
    )


def create_paystack_credit_checkout(user, pack_size: int, amount_naira: int) -> Dict[str, Any]:
    """Create a Paystack checkout for credit pack purchase."""
    base_url = os.getenv('BASE_URL', 'https://devopsagent.io')
    callback_url = f'{base_url}/billing/success?gateway=paystack'

    return PaystackPaymentService.initialize_transaction(
        email=user.email,
        amount_naira=amount_naira,
        callback_url=callback_url,
        metadata={
            'product_type': 'credit_pack',
            'pack_size': str(pack_size),
            'user_id': user.id,
        },
    )
