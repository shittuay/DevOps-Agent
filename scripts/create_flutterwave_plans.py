"""
Create payment plans on Flutterwave and store plan_ids in NGNPriceConfig.
Idempotent — skips plans that already have a flutterwave_plan_id.

Requires: FLUTTERWAVE_SECRET_KEY environment variable.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app, db
from models import NGNPriceConfig
from services.flutterwave_integration import FlutterwavePaymentService

PLAN_NAMES = {
    'starter': 'DevOps Agent Starter (NGN)',
    'professional': 'DevOps Agent Professional (NGN)',
    'business': 'DevOps Agent Business (NGN)',
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
            if config.flutterwave_plan_id:
                print(f"  {config.product_key}: already has plan_id {config.flutterwave_plan_id}, skipping")
                continue

            plan_name = PLAN_NAMES.get(config.product_key, f'DevOps Agent {config.product_key.title()} (NGN)')
            result = FlutterwavePaymentService.create_payment_plan(
                name=plan_name,
                amount_naira=config.price_ngn,
                interval='monthly',
            )

            if result['success']:
                config.flutterwave_plan_id = result['plan_id']
                db.session.commit()
                print(f"  {config.product_key}: created plan {result['plan_id']} (₦{config.price_ngn:,}/mo)")
            else:
                print(f"  {config.product_key}: FAILED — {result['error']}")

        print("\nDone.")


if __name__ == '__main__':
    if not os.getenv('FLUTTERWAVE_SECRET_KEY'):
        print("Error: FLUTTERWAVE_SECRET_KEY not set. Set it in .env or environment.")
        sys.exit(1)
    create_plans()
