#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for Stripe integration
Verifies that Stripe is properly configured and can create checkout sessions
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

def test_stripe_configuration():
    """Test that Stripe is properly configured"""
    print("=" * 60)
    print("Testing Stripe Configuration")
    print("=" * 60)

    # Check if Stripe is installed
    try:
        import stripe
        print("✓ Stripe library is installed")
        print(f"  Version: {stripe.__version__}")
    except ImportError:
        print("✗ Stripe library is not installed")
        print("  Run: pip install stripe")
        return False

    # Check API key
    api_key = os.getenv('STRIPE_SECRET_KEY')
    if not api_key:
        print("✗ STRIPE_SECRET_KEY not found in environment")
        return False

    if api_key.startswith('sk_test_'):
        print("✓ Using test API key (recommended for development)")
    elif api_key.startswith('sk_live_'):
        print("⚠ Using LIVE API key - be careful!")
    else:
        print("✗ Invalid API key format")
        return False

    print(f"  Key: {api_key[:15]}...{api_key[-4:]}")

    # Initialize Stripe
    stripe.api_key = api_key

    # Test API connection
    try:
        balance = stripe.Balance.retrieve()
        print("✓ Successfully connected to Stripe API")
        print(f"  Account mode: {'Test' if api_key.startswith('sk_test_') else 'Live'}")
    except stripe.error.AuthenticationError:
        print("✗ Authentication failed - invalid API key")
        return False
    except Exception as e:
        print(f"✗ Error connecting to Stripe: {str(e)}")
        return False

    # Check price IDs
    print("\n" + "=" * 60)
    print("Checking Price IDs")
    print("=" * 60)

    price_ids = {
        'Starter Subscription': os.getenv('STRIPE_PRICE_STARTER'),
        'Professional Subscription': os.getenv('STRIPE_PRICE_PROFESSIONAL'),
        'Business Subscription': os.getenv('STRIPE_PRICE_BUSINESS'),
        '100 Credits Pack': os.getenv('STRIPE_PRICE_PACK_100'),
        '250 Credits Pack': os.getenv('STRIPE_PRICE_PACK_250'),
        '500 Credits Pack': os.getenv('STRIPE_PRICE_PACK_500'),
        '1000 Credits Pack': os.getenv('STRIPE_PRICE_PACK_1000'),
    }

    all_valid = True
    for name, price_id in price_ids.items():
        if not price_id or price_id.startswith('price_') and len(price_id) < 20:
            print(f"⚠ {name}: Not configured or placeholder")
            all_valid = False
        else:
            # Try to retrieve the price
            try:
                price = stripe.Price.retrieve(price_id)
                amount = price.unit_amount / 100 if price.unit_amount else 0
                currency = price.currency.upper()
                interval = f" ({price.recurring['interval']})" if price.recurring else " (one-time)"
                print(f"✓ {name}: {currency} {amount:.2f}{interval}")
            except stripe.error.InvalidRequestError:
                print(f"✗ {name}: Invalid price ID '{price_id}'")
                all_valid = False
            except Exception as e:
                print(f"✗ {name}: Error - {str(e)}")
                all_valid = False

    if not all_valid:
        print("\n⚠ Some price IDs are not configured correctly")
        print("  Please create products in Stripe Dashboard and update .env")

    return all_valid


def test_checkout_session():
    """Test creating a checkout session"""
    print("\n" + "=" * 60)
    print("Testing Checkout Session Creation")
    print("=" * 60)

    try:
        import stripe
        from stripe_integration import StripePaymentService

        # Get a valid price ID
        price_id = os.getenv('STRIPE_PRICE_PACK_100')

        if not price_id or price_id.startswith('price_') and len(price_id) < 20:
            print("⚠ Cannot test checkout - no valid price ID configured")
            print("  Please configure STRIPE_PRICE_PACK_100 in .env")
            return False

        # Create a test checkout session
        result = StripePaymentService.create_checkout_session_credits(
            user_email='test@example.com',
            pack_size=100,
            pack_price_id=price_id,
            success_url='http://localhost:5000/billing/success',
            cancel_url='http://localhost:5000/billing'
        )

        if result['success']:
            print("✓ Successfully created checkout session")
            print(f"  Session ID: {result['session_id']}")
            print(f"  Checkout URL: {result['checkout_url'][:50]}...")
            return True
        else:
            print(f"✗ Failed to create checkout session: {result.get('error')}")
            return False

    except Exception as e:
        print(f"✗ Error testing checkout: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_webhook_verification():
    """Test webhook signature verification"""
    print("\n" + "=" * 60)
    print("Testing Webhook Configuration")
    print("=" * 60)

    webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')

    if not webhook_secret:
        print("⚠ STRIPE_WEBHOOK_SECRET not configured")
        print("  This is required to verify webhook events")
        print("  Run: stripe listen --forward-to localhost:5000/api/stripe/webhook")
        return False

    if webhook_secret.startswith('whsec_'):
        print("✓ Webhook secret is configured")
        print(f"  Secret: {webhook_secret[:15]}...{webhook_secret[-4:]}")
        return True
    else:
        print("✗ Invalid webhook secret format")
        return False


def print_next_steps():
    """Print next steps for the user"""
    print("\n" + "=" * 60)
    print("Next Steps")
    print("=" * 60)
    print("\n1. Create Products in Stripe Dashboard:")
    print("   - Go to https://dashboard.stripe.com/test/products")
    print("   - Create subscription products (Starter, Professional, Business)")
    print("   - Create one-time products (credit packs)")
    print("   - Copy the Price IDs to your .env file")

    print("\n2. Set up webhooks for local testing:")
    print("   - Install Stripe CLI: https://stripe.com/docs/stripe-cli")
    print("   - Run: stripe listen --forward-to localhost:5000/api/stripe/webhook")
    print("   - Copy the webhook secret to your .env file")

    print("\n3. Start your application:")
    print("   - Run: python app.py")
    print("   - Navigate to: http://localhost:5000/billing")

    print("\n4. Test a payment:")
    print("   - Click on a subscription or credit pack")
    print("   - Use test card: 4242 4242 4242 4242")
    print("   - Any future expiration date and CVC")

    print("\n5. Monitor webhooks:")
    print("   - Watch the Stripe CLI terminal for webhook events")
    print("   - Check your application logs")
    print("   - Verify credits in the billing page")

    print("\nFor detailed instructions, see STRIPE_INTEGRATION_GUIDE.md")
    print("=" * 60)


def main():
    """Run all tests"""
    print("\nStripe Integration Test Suite\n")

    tests = [
        ("Configuration", test_stripe_configuration),
        ("Checkout Session", test_checkout_session),
        ("Webhook Setup", test_webhook_verification),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n✗ Test '{test_name}' crashed: {str(e)}")
            results.append((test_name, False))

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status} - {test_name}")

    passed = sum(1 for _, r in results if r)
    total = len(results)

    print(f"\nPassed: {passed}/{total}")

    if passed == total:
        print("\n🎉 All tests passed! Stripe is ready to use.")
    else:
        print("\n⚠ Some tests failed. Please review the errors above.")
        print_next_steps()

    print("\n" + "=" * 60)


if __name__ == '__main__':
    main()
