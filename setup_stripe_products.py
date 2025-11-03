#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Helper script to create Stripe products and prices
This will automatically create all products needed for the DevOps Agent
"""
import os
import sys
from dotenv import load_dotenv

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Load environment variables
load_dotenv('config/.env')

try:
    import stripe
except ImportError:
    print("Error: Stripe library not installed")
    print("Run: pip install stripe")
    sys.exit(1)

# Initialize Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

def create_subscription_product(name, description, price_usd, credits):
    """Create a subscription product"""
    try:
        # Create product
        product = stripe.Product.create(
            name=name,
            description=description,
            metadata={
                'credits': credits,
                'type': 'subscription'
            }
        )

        # Create price
        price = stripe.Price.create(
            product=product.id,
            unit_amount=int(price_usd * 100),  # Convert to cents
            currency='usd',
            recurring={'interval': 'month'}
        )

        return {
            'success': True,
            'product_id': product.id,
            'price_id': price.id,
            'name': name
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'name': name
        }

def create_credit_pack_product(credits, price_usd):
    """Create a credit pack product"""
    try:
        # Create product
        product = stripe.Product.create(
            name=f'{credits} Credits',
            description=f'One-time purchase of {credits} credits',
            metadata={
                'credits': credits,
                'type': 'credit_pack'
            }
        )

        # Create price
        price = stripe.Price.create(
            product=product.id,
            unit_amount=int(price_usd * 100),  # Convert to cents
            currency='usd'
        )

        return {
            'success': True,
            'product_id': product.id,
            'price_id': price.id,
            'name': f'{credits} Credits'
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'name': f'{credits} Credits'
        }

def main():
    """Create all products"""
    print("\n" + "=" * 60)
    print("Stripe Product Setup for DevOps Agent")
    print("=" * 60)

    # Check API key
    api_key = os.getenv('STRIPE_SECRET_KEY')
    if not api_key:
        print("\nError: STRIPE_SECRET_KEY not found in config/.env")
        print("Please add your Stripe secret key first.")
        sys.exit(1)

    if api_key.startswith('sk_test_'):
        print("\n✓ Using test mode (recommended)")
    elif api_key.startswith('sk_live_'):
        print("\n⚠ WARNING: Using LIVE mode - real money will be involved!")
        response = input("Are you sure you want to create products in live mode? (yes/no): ")
        if response.lower() != 'yes':
            print("Aborted.")
            sys.exit(0)
    else:
        print("\nError: Invalid API key format")
        sys.exit(1)

    print("\nThis will create the following products in Stripe:")
    print("\nSubscriptions:")
    print("  - Starter Plan: $9.99/month (100 credits)")
    print("  - Professional Plan: $29.99/month (500 credits)")
    print("  - Business Plan: $99.99/month (2000 credits)")
    print("\nCredit Packs:")
    print("  - 100 Credits: $10.00")
    print("  - 250 Credits: $20.00")
    print("  - 500 Credits: $35.00")
    print("  - 1000 Credits: $60.00")

    response = input("\nProceed? (yes/no): ")
    if response.lower() != 'yes':
        print("Aborted.")
        sys.exit(0)

    print("\n" + "=" * 60)
    print("Creating Products...")
    print("=" * 60)

    # Create subscription products
    subscriptions = [
        ('Starter Plan', 'Perfect for individuals - 100 credits per month', 9.99, 100),
        ('Professional Plan', 'For growing teams - 500 credits per month', 29.99, 500),
        ('Business Plan', 'For enterprises - 2000 credits per month', 99.99, 2000),
    ]

    subscription_results = []
    for name, desc, price, credits in subscriptions:
        print(f"\nCreating {name}...")
        result = create_subscription_product(name, desc, price, credits)
        subscription_results.append(result)
        if result['success']:
            print(f"  ✓ Created: {result['price_id']}")
        else:
            print(f"  ✗ Failed: {result['error']}")

    # Create credit pack products
    credit_packs = [
        (100, 10.00),
        (250, 20.00),
        (500, 35.00),
        (1000, 60.00),
    ]

    pack_results = []
    for credits, price in credit_packs:
        print(f"\nCreating {credits} Credits pack...")
        result = create_credit_pack_product(credits, price)
        pack_results.append(result)
        if result['success']:
            print(f"  ✓ Created: {result['price_id']}")
        else:
            print(f"  ✗ Failed: {result['error']}")

    # Generate .env configuration
    print("\n" + "=" * 60)
    print("Configuration for .env file")
    print("=" * 60)

    print("\n# Add these to your config/.env file:\n")

    if len(subscription_results) >= 3:
        if subscription_results[0]['success']:
            print(f"STRIPE_PRICE_STARTER={subscription_results[0]['price_id']}")
        if subscription_results[1]['success']:
            print(f"STRIPE_PRICE_PROFESSIONAL={subscription_results[1]['price_id']}")
        if subscription_results[2]['success']:
            print(f"STRIPE_PRICE_BUSINESS={subscription_results[2]['price_id']}")

    print()

    if len(pack_results) >= 4:
        if pack_results[0]['success']:
            print(f"STRIPE_PRICE_PACK_100={pack_results[0]['price_id']}")
        if pack_results[1]['success']:
            print(f"STRIPE_PRICE_PACK_250={pack_results[1]['price_id']}")
        if pack_results[2]['success']:
            print(f"STRIPE_PRICE_PACK_500={pack_results[2]['price_id']}")
        if pack_results[3]['success']:
            print(f"STRIPE_PRICE_PACK_1000={pack_results[3]['price_id']}")

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    success_count = sum(1 for r in subscription_results + pack_results if r['success'])
    total_count = len(subscription_results) + len(pack_results)

    print(f"\nCreated {success_count}/{total_count} products successfully")

    if success_count == total_count:
        print("\n✓ All products created successfully!")
        print("\nNext steps:")
        print("1. Copy the price IDs above to your config/.env file")
        print("2. Run: python test_stripe.py")
        print("3. Start your app: python app.py")
    else:
        print("\n⚠ Some products failed to create. Please review errors above.")

    print("\n" + "=" * 60)

if __name__ == '__main__':
    main()
