"""
Create subscription plans on Paystack and store plan_codes in NGNPriceConfig.
Idempotent — skips plans that already have a paystack_plan_code.

Requires: PAYSTACK_SECRET_KEY environment variable.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app, db
from models import NGNPriceConfig
from services.paystack_integration import PaystackPaymentService

PLAN_NAMES = {
    'starter': 'DevOps Agent Starter',
    'professional': 'DevOps Agent Professional',
    'business': 'DevOps Agent Business',
}


def create_plans():
    with app.app_context():
        configs = NGNPriceConfig.query.filter_by(
            product_type='subscription', is_active=True
        ).all()

        if not configs:
            print("No NGN subscription configs found. Run seed_ngn_prices.py first.")
            return

        for config in configs:
            if config.paystack_plan_code:
                print(f"  {config.product_key}: already has plan_code {config.paystack_plan_code}, skipping")
                continue

            plan_name = PLAN_NAMES.get(config.product_key, f'DevOps Agent {config.product_key.title()}')
            result = PaystackPaymentService.create_plan(
                name=plan_name,
                amount_naira=config.price_ngn,
                interval='monthly',
            )

            if result['success']:
                config.paystack_plan_code = result['plan_code']
                db.session.commit()
                print(f"  {config.product_key}: created plan {result['plan_code']} (₦{config.price_ngn:,}/mo)")
            else:
                print(f"  {config.product_key}: FAILED — {result['error']}")

        print("\nDone.")


if __name__ == '__main__':
    if not os.getenv('PAYSTACK_SECRET_KEY'):
        print("Error: PAYSTACK_SECRET_KEY not set. Set it in .env or environment.")
        sys.exit(1)
    create_plans()
