"""
Flutterwave Payment Integration for DevOps Agent
Fallback NGN payment gateway when Paystack is unavailable.
"""
import os
import hmac
import hashlib
import logging
import uuid
import requests
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

FLUTTERWAVE_BASE_URL = 'https://api.flutterwave.com/v3'


def _get_secret_key() -> str:
    key = os.getenv('FLUTTERWAVE_SECRET_KEY')
    if not key:
        raise RuntimeError('FLUTTERWAVE_SECRET_KEY is not set in environment')
    return key


def _headers() -> Dict[str, str]:
    return {
        'Authorization': f'Bearer {_get_secret_key()}',
        'Content-Type': 'application/json',
    }


def _generate_reference() -> str:
    return f'da-fw-{uuid.uuid4().hex[:12]}'


class FlutterwavePaymentService:
    """Service for handling Flutterwave payments (NGN)."""

    @staticmethod
    def initialize_payment(
        email: str,
        amount_naira: int,
        redirect_url: str,
        metadata: Optional[Dict[str, Any]] = None,
        reference: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Initialize a Flutterwave payment.

        Args:
            email: Customer email
            amount_naira: Amount in whole naira (NOT kobo — Flutterwave uses naira directly)
            redirect_url: URL to redirect after payment
            metadata: Additional metadata
            reference: Optional payment reference
        """
        try:
            ref = reference or _generate_reference()
            payload = {
                'tx_ref': ref,
                'amount': amount_naira,  # Flutterwave uses naira directly, NOT kobo
                'currency': 'NGN',
                'redirect_url': redirect_url,
                'customer': {'email': email},
                'meta': metadata or {},
                'payment_options': 'card,banktransfer,ussd',
            }

            resp = requests.post(
                f'{FLUTTERWAVE_BASE_URL}/payments',
                json=payload,
                headers=_headers(),
                timeout=30,
            )
            data = resp.json()

            if data.get('status') == 'success':
                return {
                    'success': True,
                    'payment_link': data['data']['link'],
                    'reference': ref,
                }
            else:
                logger.error(f"Flutterwave init failed: {data.get('message')}")
                return {'success': False, 'error': data.get('message', 'Payment initialization failed')}

        except Exception as e:
            logger.error(f"Flutterwave initialize_payment error: {e}")
            return {'success': False, 'error': str(e)}

    @staticmethod
    def verify_transaction(transaction_id: str) -> Dict[str, Any]:
        """Verify a Flutterwave transaction by ID."""
        try:
            resp = requests.get(
                f'{FLUTTERWAVE_BASE_URL}/transactions/{transaction_id}/verify',
                headers=_headers(),
                timeout=30,
            )
            data = resp.json()

            if data.get('status') == 'success' and data['data'].get('status') == 'successful':
                txn = data['data']
                return {
                    'success': True,
                    'amount': txn['amount'],
                    'currency': txn['currency'],
                    'reference': txn['tx_ref'],
                    'flw_ref': txn['flw_ref'],
                    'customer_email': txn['customer']['email'],
                    'customer_id': str(txn['customer']['id']),
                    'metadata': txn.get('meta', {}),
                    'paid_at': txn.get('created_at'),
                }
            else:
                status = data.get('data', {}).get('status', 'unknown')
                return {'success': False, 'error': f'Transaction not successful (status: {status})'}

        except Exception as e:
            logger.error(f"Flutterwave verify_transaction error: {e}")
            return {'success': False, 'error': str(e)}

    @staticmethod
    def verify_transaction_by_ref(tx_ref: str) -> Dict[str, Any]:
        """Verify a Flutterwave transaction by tx_ref (reference)."""
        try:
            resp = requests.get(
                f'{FLUTTERWAVE_BASE_URL}/transactions',
                params={'tx_ref': tx_ref},
                headers=_headers(),
                timeout=30,
            )
            data = resp.json()

            if data.get('status') == 'success' and data.get('data'):
                txn = data['data'][0] if isinstance(data['data'], list) else data['data']
                if txn.get('status') == 'successful':
                    return {
                        'success': True,
                        'transaction_id': str(txn['id']),
                        'amount': txn['amount'],
                        'currency': txn['currency'],
                        'reference': txn['tx_ref'],
                        'customer_email': txn['customer']['email'],
                        'metadata': txn.get('meta', {}),
                    }
            return {'success': False, 'error': 'Transaction not found or not successful'}

        except Exception as e:
            logger.error(f"Flutterwave verify_transaction_by_ref error: {e}")
            return {'success': False, 'error': str(e)}

    @staticmethod
    def create_payment_plan(name: str, amount_naira: int, interval: str = 'monthly') -> Dict[str, Any]:
        """Create a Flutterwave payment plan for recurring billing."""
        try:
            payload = {
                'name': name,
                'amount': amount_naira,
                'interval': interval,  # monthly, weekly, yearly
                'currency': 'NGN',
            }

            resp = requests.post(
                f'{FLUTTERWAVE_BASE_URL}/payment-plans',
                json=payload,
                headers=_headers(),
                timeout=30,
            )
            data = resp.json()

            if data.get('status') == 'success':
                return {
                    'success': True,
                    'plan_id': str(data['data']['id']),
                    'plan_name': data['data']['name'],
                }
            else:
                return {'success': False, 'error': data.get('message', 'Plan creation failed')}

        except Exception as e:
            logger.error(f"Flutterwave create_payment_plan error: {e}")
            return {'success': False, 'error': str(e)}

    @staticmethod
    def cancel_subscription(subscription_id: str) -> Dict[str, Any]:
        """Cancel a Flutterwave subscription."""
        try:
            resp = requests.put(
                f'{FLUTTERWAVE_BASE_URL}/subscriptions/{subscription_id}/cancel',
                headers=_headers(),
                timeout=30,
            )
            data = resp.json()

            if data.get('status') == 'success':
                return {'success': True}
            else:
                return {'success': False, 'error': data.get('message', 'Cancellation failed')}

        except Exception as e:
            logger.error(f"Flutterwave cancel_subscription error: {e}")
            return {'success': False, 'error': str(e)}

    @staticmethod
    def verify_webhook_signature(payload: bytes, signature: str) -> bool:
        """Verify Flutterwave webhook using the webhook secret hash."""
        secret = os.getenv('FLUTTERWAVE_WEBHOOK_SECRET', '')
        if not secret:
            logger.warning("FLUTTERWAVE_WEBHOOK_SECRET not set")
            return False
        expected = hashlib.sha256(secret.encode('utf-8')).hexdigest()
        return hmac.compare_digest(expected, signature)


# Helper functions

def create_flutterwave_subscription_checkout(user, tier_name: str, amount_naira: int, plan_id: Optional[str] = None) -> Dict[str, Any]:
    """Create a Flutterwave checkout for subscription."""
    base_url = os.getenv('BASE_URL', 'https://devopsagent.io')
    redirect_url = f'{base_url}/billing/success?gateway=flutterwave'

    return FlutterwavePaymentService.initialize_payment(
        email=user.email,
        amount_naira=amount_naira,
        redirect_url=redirect_url,
        metadata={
            'product_type': 'subscription',
            'tier_name': tier_name,
            'plan_id': plan_id or '',
            'user_id': user.id,
        },
    )


def create_flutterwave_credit_checkout(user, pack_size: int, amount_naira: int) -> Dict[str, Any]:
    """Create a Flutterwave checkout for credit pack purchase."""
    base_url = os.getenv('BASE_URL', 'https://devopsagent.io')
    redirect_url = f'{base_url}/billing/success?gateway=flutterwave'

    return FlutterwavePaymentService.initialize_payment(
        email=user.email,
        amount_naira=amount_naira,
        redirect_url=redirect_url,
        metadata={
            'product_type': 'credit_pack',
            'pack_size': str(pack_size),
            'user_id': user.id,
        },
    )
