"""
Create Stripe products and prices, then update AWS Secrets Manager.
Run on the server where STRIPE_SECRET_KEY is available.
"""
import os
import sys
import json
import stripe
import boto3

# Load Stripe key from environment
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
if not stripe.api_key:
    print("ERROR: STRIPE_SECRET_KEY not set")
    sys.exit(1)

print(f"Using Stripe key: {stripe.api_key[:12]}...")

# Define products and prices
SUBSCRIPTION_PLANS = [
    {'name': 'DevOps Agent - Starter', 'price': 4900, 'env_key': 'STRIPE_PRICE_STARTER',
     'interval': 'month', 'description': 'Starter plan - 200 AI messages/month'},
    {'name': 'DevOps Agent - Professional', 'price': 19900, 'env_key': 'STRIPE_PRICE_PROFESSIONAL',
     'interval': 'month', 'description': 'Pro plan - 2,000 AI messages/month'},
    {'name': 'DevOps Agent - Enterprise', 'price': 79900, 'env_key': 'STRIPE_PRICE_BUSINESS',
     'interval': 'month', 'description': 'Enterprise plan - Unlimited AI messages'},
]

CREDIT_PACKS = [
    {'name': 'DevOps Agent - 100 Credits', 'price': 1000, 'env_key': 'STRIPE_PRICE_PACK_100',
     'description': '100 AI credit pack'},
    {'name': 'DevOps Agent - 250 Credits', 'price': 2000, 'env_key': 'STRIPE_PRICE_PACK_250',
     'description': '250 AI credit pack'},
    {'name': 'DevOps Agent - 500 Credits', 'price': 3500, 'env_key': 'STRIPE_PRICE_PACK_500',
     'description': '500 AI credit pack'},
    {'name': 'DevOps Agent - 1000 Credits', 'price': 6000, 'env_key': 'STRIPE_PRICE_PACK_1000',
     'description': '1000 AI credit pack'},
]

new_price_ids = {}

# Create subscription products and prices
print("\n=== Creating Subscription Plans ===")
for plan in SUBSCRIPTION_PLANS:
    try:
        product = stripe.Product.create(
            name=plan['name'],
            description=plan['description'],
        )
        price = stripe.Price.create(
            product=product.id,
            unit_amount=plan['price'],
            currency='usd',
            recurring={'interval': plan['interval']},
        )
        new_price_ids[plan['env_key']] = price.id
        print(f"  {plan['env_key']}: {price.id} (${plan['price']/100}/month)")
    except Exception as e:
        print(f"  ERROR creating {plan['name']}: {e}")
        sys.exit(1)

# Create credit pack products and prices
print("\n=== Creating Credit Packs ===")
for pack in CREDIT_PACKS:
    try:
        product = stripe.Product.create(
            name=pack['name'],
            description=pack['description'],
        )
        price = stripe.Price.create(
            product=product.id,
            unit_amount=pack['price'],
            currency='usd',
        )
        new_price_ids[pack['env_key']] = price.id
        print(f"  {pack['env_key']}: {price.id} (${pack['price']/100})")
    except Exception as e:
        print(f"  ERROR creating {pack['name']}: {e}")
        sys.exit(1)

print(f"\n=== All {len(new_price_ids)} prices created ===")
for k, v in new_price_ids.items():
    print(f"  {k}={v}")

# Update AWS Secrets Manager
print("\n=== Updating AWS Secrets Manager ===")
try:
    sm = boto3.client('secretsmanager', region_name='us-east-1')
    secret_name = 'devops-agent/production'

    # Get current secret
    response = sm.get_secret_value(SecretId=secret_name)
    secrets = json.loads(response['SecretString'])

    # Update with new price IDs
    secrets.update(new_price_ids)

    # Write back
    sm.update_secret(SecretId=secret_name, SecretString=json.dumps(secrets))
    print(f"  Updated {secret_name} with {len(new_price_ids)} new price IDs")

    # Verify
    verify = sm.get_secret_value(SecretId=secret_name)
    verify_secrets = json.loads(verify['SecretString'])
    for key in new_price_ids:
        if verify_secrets.get(key) == new_price_ids[key]:
            print(f"  Verified: {key}")
        else:
            print(f"  MISMATCH: {key}")

except Exception as e:
    print(f"  ERROR updating secrets: {e}")
    print("\n  Manual update needed. Add these to AWS Secrets Manager:")
    print(f"  Secret: {secret_name}")
    for k, v in new_price_ids.items():
        print(f'    "{k}": "{v}"')
    sys.exit(1)

print("\nDone! Restart the app to pick up new prices.")
