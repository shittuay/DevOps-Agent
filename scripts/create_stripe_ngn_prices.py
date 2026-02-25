"""
Create Stripe products and prices for NGN (Nigerian Naira) products.
Reads amounts from NGNPriceConfig table, creates Stripe Price objects in NGN currency,
and stores the Stripe Price ID back in NGNPriceConfig.stripe_price_id_ngn.

Idempotent: skips creation if NGN price ID is already set and active at the correct amount.

Usage:
    python scripts/create_stripe_ngn_prices.py

Requires:
    - STRIPE_SECRET_KEY in env or AWS Secrets Manager
    - NGNPriceConfig table seeded (run scripts/seed_ngn_prices.py first)
    - App database accessible
"""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stripe

# Load Stripe key
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
if not stripe.api_key:
    print("STRIPE_SECRET_KEY not in env, trying AWS Secrets Manager...")
    try:
        import boto3
        import json
        sm = boto3.client('secretsmanager', region_name='us-east-1')
        response = sm.get_secret_value(SecretId='devops-agent/production')
        secrets = json.loads(response['SecretString'])
        stripe.api_key = secrets.get('STRIPE_SECRET_KEY')
    except Exception as e:
        print(f"Failed to load from Secrets Manager: {e}")
if not stripe.api_key:
    print("ERROR: STRIPE_SECRET_KEY not found in env or Secrets Manager")
    sys.exit(1)

print(f"Using Stripe key: {stripe.api_key[:12]}...")

# Initialize Flask app to access database
from app import app, db
from models import NGNPriceConfig

# Product name mapping
PRODUCT_NAMES = {
    'starter': 'DevOps Agent - Starter (NGN)',
    'professional': 'DevOps Agent - Professional (NGN)',
    'business': 'DevOps Agent - Business (NGN)',
    'pack_100': 'DevOps Agent - 100 Credits (NGN)',
    'pack_250': 'DevOps Agent - 250 Credits (NGN)',
    'pack_500': 'DevOps Agent - 500 Credits (NGN)',
    'pack_1000': 'DevOps Agent - 1000 Credits (NGN)',
}

with app.app_context():
    configs = NGNPriceConfig.query.filter_by(is_active=True).all()
    if not configs:
        print("ERROR: No active NGN price configs found. Run scripts/seed_ngn_prices.py first.")
        sys.exit(1)

    created = 0
    skipped = 0

    for config in configs:
        # Amount in smallest currency unit (kobo = naira * 100)
        amount_kobo = config.price_ngn * 100
        is_subscription = config.product_type == 'subscription'
        product_name = PRODUCT_NAMES.get(config.product_key, f'DevOps Agent - {config.product_key} (NGN)')

        # Check if existing price ID is still valid
        if config.stripe_price_id_ngn:
            try:
                existing = stripe.Price.retrieve(config.stripe_price_id_ngn)
                if existing.active and existing.unit_amount == amount_kobo and existing.currency == 'ngn':
                    print(f"  {config.product_key}: {config.stripe_price_id_ngn} (NGN {config.price_ngn:,}) -- already active, skipping")
                    skipped += 1
                    continue
            except Exception:
                pass  # Price doesn't exist or API error, create new one

        # Create Stripe product + price
        try:
            product = stripe.Product.create(
                name=product_name,
                description=f'{product_name} - NGN {config.price_ngn:,}',
            )
            price_params = {
                'product': product.id,
                'unit_amount': amount_kobo,
                'currency': 'ngn',
            }
            if is_subscription:
                price_params['recurring'] = {'interval': 'month'}

            price = stripe.Price.create(**price_params)

            # Store price ID back in database
            config.stripe_price_id_ngn = price.id
            db.session.commit()

            label = f"NGN {config.price_ngn:,}/month" if is_subscription else f"NGN {config.price_ngn:,}"
            print(f"  {config.product_key}: {price.id} ({label}) -- CREATED")
            created += 1

        except Exception as e:
            print(f"  ERROR creating {config.product_key}: {e}")
            sys.exit(1)

    print(f"\n=== {created} created, {skipped} already active (total: {len(configs)}) ===")

    if created == 0:
        print("All NGN prices are already active. Nothing to update.")
    else:
        print("\nNGN Stripe prices created and stored in NGNPriceConfig.stripe_price_id_ngn.")
        print("Restart the app to pick up new prices.")
