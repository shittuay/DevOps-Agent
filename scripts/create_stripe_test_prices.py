"""
Create Stripe test prices and update config/.env only.
Safe to run — never touches AWS Secrets Manager or production prices.
"""
import os
import sys
import re

# Load test key from config/.env
env_path = os.path.join(os.path.dirname(__file__), '..', 'config', '.env')
env_vars = {}
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if '=' in line and not line.startswith('#'):
            k, _, v = line.partition('=')
            env_vars[k.strip()] = v.strip()

stripe_key = env_vars.get('STRIPE_SECRET_KEY', '')
if not stripe_key.startswith('sk_test_'):
    print("ERROR: STRIPE_SECRET_KEY in config/.env is not a test key (must start with sk_test_)")
    sys.exit(1)

import stripe
stripe.api_key = stripe_key
print(f"Using test key: {stripe_key[:16]}...")

PLANS = [
    {'name': 'DevOps Agent - Starter',      'price': 2900,  'key': 'STRIPE_PRICE_STARTER',       'interval': 'month'},
    {'name': 'DevOps Agent - Professional',  'price': 9900,  'key': 'STRIPE_PRICE_PROFESSIONAL',   'interval': 'month'},
    {'name': 'DevOps Agent - Enterprise',    'price': 29900, 'key': 'STRIPE_PRICE_BUSINESS',       'interval': 'month'},
]

PACKS = [
    {'name': 'DevOps Agent - 100 Credits',  'price': 1000, 'key': 'STRIPE_PRICE_PACK_100'},
    {'name': 'DevOps Agent - 250 Credits',  'price': 2000, 'key': 'STRIPE_PRICE_PACK_250'},
    {'name': 'DevOps Agent - 500 Credits',  'price': 3500, 'key': 'STRIPE_PRICE_PACK_500'},
    {'name': 'DevOps Agent - 1000 Credits', 'price': 6000, 'key': 'STRIPE_PRICE_PACK_1000'},
]

new_prices = {}

print("\n=== Subscription Plans ===")
for plan in PLANS:
    try:
        product = stripe.Product.create(name=plan['name'])
        price = stripe.Price.create(
            product=product.id,
            unit_amount=plan['price'],
            currency='usd',
            recurring={'interval': plan['interval']},
        )
        new_prices[plan['key']] = price.id
        print(f"  {plan['key']}: {price.id}  (${plan['price']/100}/mo) — CREATED")
    except Exception as e:
        print(f"  ERROR: {plan['name']}: {e}")
        sys.exit(1)

print("\n=== Credit Packs ===")
for pack in PACKS:
    try:
        product = stripe.Product.create(name=pack['name'])
        price = stripe.Price.create(
            product=product.id,
            unit_amount=pack['price'],
            currency='usd',
        )
        new_prices[pack['key']] = price.id
        print(f"  {pack['key']}: {price.id}  (${pack['price']/100}) — CREATED")
    except Exception as e:
        print(f"  ERROR: {pack['name']}: {e}")
        sys.exit(1)

# Update config/.env in-place
print("\n=== Updating config/.env ===")
with open(env_path, 'r') as f:
    content = f.read()

for key, value in new_prices.items():
    # Replace existing value or append
    if re.search(rf'^{key}=', content, re.MULTILINE):
        content = re.sub(rf'^{key}=.*$', f'{key}={value}', content, flags=re.MULTILINE)
    else:
        content += f'\n{key}={value}'

with open(env_path, 'w') as f:
    f.write(content)

print("  config/.env updated with test price IDs")
print("\nDone! Restart the app to pick up new prices.")
