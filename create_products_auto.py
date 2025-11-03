#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Automatic product creation (non-interactive)
"""
import os
import sys
from dotenv import load_dotenv

if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

load_dotenv('config/.env')

try:
    import stripe
except ImportError:
    print("Error: pip install stripe")
    sys.exit(1)

stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

def create_products():
    """Create all products automatically"""
    print("\nCreating Stripe products...")

    products = []

    # Subscriptions
    subs = [
        ('Starter Plan', 'Perfect for individuals - 100 credits per month', 9.99, 100, 'starter'),
        ('Professional Plan', 'For growing teams - 500 credits per month', 29.99, 500, 'professional'),
        ('Business Plan', 'For enterprises - 2000 credits per month', 99.99, 2000, 'business'),
    ]

    for name, desc, price, credits, key in subs:
        try:
            product = stripe.Product.create(name=name, description=desc)
            price_obj = stripe.Price.create(
                product=product.id,
                unit_amount=int(price * 100),
                currency='usd',
                recurring={'interval': 'month'}
            )
            products.append((f'STRIPE_PRICE_{key.upper()}', price_obj.id))
            print(f"✓ Created {name}: {price_obj.id}")
        except Exception as e:
            print(f"✗ Failed {name}: {e}")

    # Credit packs
    packs = [(100, 10.00), (250, 20.00), (500, 35.00), (1000, 60.00)]

    for credits, price in packs:
        try:
            product = stripe.Product.create(
                name=f'{credits} Credits',
                description=f'One-time purchase of {credits} credits'
            )
            price_obj = stripe.Price.create(
                product=product.id,
                unit_amount=int(price * 100),
                currency='usd'
            )
            products.append((f'STRIPE_PRICE_PACK_{credits}', price_obj.id))
            print(f"✓ Created {credits} Credits: {price_obj.id}")
        except Exception as e:
            print(f"✗ Failed {credits} Credits: {e}")

    print("\n# Add to config/.env:")
    for key, value in products:
        print(f"{key}={value}")

if __name__ == '__main__':
    create_products()
