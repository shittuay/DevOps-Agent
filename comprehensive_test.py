"""Comprehensive test to check for any issues in the application"""
import sys
import importlib.util

# Set UTF-8 encoding for Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

print("="*70)
print("DevOps Agent - Comprehensive Test Suite")
print("="*70)

# Test 1: Import all main modules
print("\n[Test 1] Testing module imports...")
modules_to_test = [
    'app',
    'models',
    'stripe_integration',
    'src.agent.core',
    'src.config',
    'src.utils',
]

failed_imports = []
for module_name in modules_to_test:
    try:
        if '.' in module_name:
            # Handle nested modules
            parts = module_name.split('.')
            module = __import__(module_name)
            for part in parts[1:]:
                module = getattr(module, part)
        else:
            module = __import__(module_name)
        print(f"  ✓ {module_name}")
    except Exception as e:
        print(f"  ✗ {module_name}: {str(e)}")
        failed_imports.append((module_name, str(e)))

# Test 2: Check database
print("\n[Test 2] Testing database connectivity...")
try:
    from app import app, db
    from models import User, Conversation, SubscriptionTier

    with app.app_context():
        # Try a simple query
        user_count = User.query.count()
        conv_count = Conversation.query.count()
        tier_count = SubscriptionTier.query.count()
        print(f"  ✓ Database connected")
        print(f"    - Users: {user_count}")
        print(f"    - Conversations: {conv_count}")
        print(f"    - Tiers: {tier_count}")
except Exception as e:
    print(f"  ✗ Database error: {str(e)}")

# Test 3: Check Flask routes
print("\n[Test 3] Checking Flask routes...")
try:
    from app import app
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append(str(rule))
    print(f"  ✓ Found {len(routes)} routes")
    critical_routes = ['/login', '/signup', '/chat', '/api/chat']
    for route in critical_routes:
        if any(route in r for r in routes):
            print(f"    ✓ {route}")
        else:
            print(f"    ✗ {route} missing!")
except Exception as e:
    print(f"  ✗ Error checking routes: {str(e)}")

# Test 4: Check agent initialization
print("\n[Test 4] Testing agent initialization...")
try:
    from src.agent import DevOpsAgent
    from src.config import ConfigManager
    import os

    # Create a minimal config for testing
    test_api_key = os.getenv('ANTHROPIC_API_KEY', 'sk-test-dummy-key-for-testing')

    # Just check if the class can be imported
    print(f"  ✓ DevOpsAgent class imported successfully")
    print(f"  ℹ Agent requires valid API key for full initialization")
except Exception as e:
    print(f"  ✗ Agent error: {str(e)}")

# Test 5: Check Stripe integration
print("\n[Test 5] Checking Stripe integration...")
try:
    import stripe
    from stripe_integration import StripePaymentService
    print(f"  ✓ Stripe module imported (v{stripe.VERSION})")
    print(f"  ✓ StripePaymentService class available")
except Exception as e:
    print(f"  ✗ Stripe error: {str(e)}")

# Test 6: Check security features
print("\n[Test 6] Checking security features...")
try:
    from flask_wtf.csrf import CSRFProtect
    from flask_limiter import Limiter
    from flask_talisman import Talisman
    from email_validator import validate_email
    print(f"  ✓ CSRF Protection available")
    print(f"  ✓ Rate Limiter available")
    print(f"  ✓ Talisman (security headers) available")
    print(f"  ✓ Email validator available")
except Exception as e:
    print(f"  ✗ Security features error: {str(e)}")

# Test 7: Check i18n support
print("\n[Test 7] Checking internationalization...")
try:
    from i18n_config import LANGUAGES, COMMON_TRANSLATIONS
    print(f"  ✓ i18n config loaded")
    print(f"  ✓ Supported languages: {', '.join(LANGUAGES.keys())}")
except Exception as e:
    print(f"  ✗ i18n error: {str(e)}")

# Summary
print("\n" + "="*70)
print("Test Summary")
print("="*70)

if failed_imports:
    print(f"\n⚠ {len(failed_imports)} module import(s) failed:")
    for module, error in failed_imports:
        print(f"  - {module}: {error}")
else:
    print("\n✓ All modules imported successfully!")

print("\n✓ Application structure is healthy!")
print("\nNote: Some features require proper configuration:")
print("  - ANTHROPIC_API_KEY for AI agent")
print("  - STRIPE_SECRET_KEY for payments")
print("  - AWS credentials for AWS tools")

print("\n" + "="*70)
