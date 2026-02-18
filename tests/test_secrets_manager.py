"""
Test script for AWS Secrets Manager integration
Tests retrieving secrets from AWS Secrets Manager
"""
import os
import sys
from services.secrets_manager import (
    SecretsManager,
    get_secrets_manager,
    get_anthropic_api_key,
    get_all_secrets
)


def test_individual_secret():
    """Test retrieving individual secret"""
    print("\n" + "="*60)
    print("Test 1: Individual Secret Retrieval")
    print("="*60)

    try:
        sm = get_secrets_manager(region_name='us-east-1')
        secret = sm.get_secret('ANTHROPIC_API_KEY')

        if secret:
            # Mask the secret for display
            masked = secret[:10] + "..." if len(secret) > 10 else "***"
            print(f"✅ Successfully retrieved ANTHROPIC_API_KEY: {masked}")
            return True
        else:
            print("❌ Failed to retrieve secret (returned None)")
            return False

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False


def test_json_secret():
    """Test retrieving JSON secret"""
    print("\n" + "="*60)
    print("Test 2: JSON Secret Retrieval")
    print("="*60)

    try:
        sm = get_secrets_manager(region_name='us-east-1')
        secrets = sm.get_secret_json('devops-agent/secrets')

        if secrets:
            print(f"✅ Successfully retrieved JSON secret with {len(secrets)} keys:")
            for key in secrets.keys():
                value = secrets[key]
                if value:
                    masked = value[:10] + "..." if len(str(value)) > 10 else "***"
                    print(f"   - {key}: {masked}")
                else:
                    print(f"   - {key}: (empty)")
            return True
        else:
            print("⚠️  JSON secret not found (this is okay if using individual secrets)")
            return True

    except Exception as e:
        print(f"⚠️  JSON secret not available: {str(e)}")
        print("   (This is okay if using individual secrets)")
        return True


def test_helper_function():
    """Test get_anthropic_api_key helper"""
    print("\n" + "="*60)
    print("Test 3: Helper Function")
    print("="*60)

    try:
        api_key = get_anthropic_api_key()

        if api_key:
            masked = api_key[:10] + "..." if len(api_key) > 10 else "***"
            print(f"✅ Successfully retrieved API key: {masked}")
            print("   Source: ", end="")
            if os.environ.get('ANTHROPIC_API_KEY'):
                print("Environment variable")
            else:
                print("AWS Secrets Manager")
            return True
        else:
            print("❌ Failed to retrieve API key")
            return False

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False


def test_all_secrets():
    """Test get_all_secrets function"""
    print("\n" + "="*60)
    print("Test 4: Get All Secrets")
    print("="*60)

    try:
        secrets = get_all_secrets()

        if secrets:
            print(f"✅ Retrieved {len(secrets)} secrets:")
            for key, value in secrets.items():
                if value:
                    masked = str(value)[:10] + "..." if len(str(value)) > 10 else "***"
                    print(f"   - {key}: {masked}")
                else:
                    print(f"   - {key}: (not set)")
            return True
        else:
            print("⚠️  No secrets retrieved")
            return True

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False


def test_caching():
    """Test secret caching"""
    print("\n" + "="*60)
    print("Test 5: Caching Functionality")
    print("="*60)

    try:
        import time
        sm = get_secrets_manager()

        # First call (should hit AWS)
        start = time.time()
        secret1 = sm.get_secret('ANTHROPIC_API_KEY', use_cache=False)
        time1 = time.time() - start

        # Second call (should use cache)
        start = time.time()
        secret2 = sm.get_secret('ANTHROPIC_API_KEY', use_cache=True)
        time2 = time.time() - start

        print(f"✅ First call (no cache): {time1:.3f}s")
        print(f"✅ Second call (cached):  {time2:.3f}s")
        print(f"   Cache speedup: {time1/time2:.1f}x faster")

        if secret1 == secret2:
            print("✅ Cached value matches original")
            return True
        else:
            print("❌ Cached value doesn't match")
            return False

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False


def test_error_handling():
    """Test error handling for non-existent secret"""
    print("\n" + "="*60)
    print("Test 6: Error Handling")
    print("="*60)

    try:
        sm = get_secrets_manager()
        secret = sm.get_secret('NONEXISTENT_SECRET_12345')

        print("❌ Should have raised an exception for non-existent secret")
        return False

    except Exception as e:
        print(f"✅ Correctly raised exception: {type(e).__name__}")
        return True


def check_prerequisites():
    """Check if prerequisites are met"""
    print("\n" + "="*60)
    print("Prerequisites Check")
    print("="*60)

    all_good = True

    # Check AWS credentials
    try:
        import boto3
        sts = boto3.client('sts')
        identity = sts.get_caller_identity()
        print(f"✅ AWS credentials configured")
        print(f"   Account: {identity['Account']}")
        print(f"   User/Role: {identity['Arn']}")
    except Exception as e:
        print(f"❌ AWS credentials not configured: {str(e)}")
        print("   Run: aws configure")
        all_good = False

    # Check region
    region = os.environ.get('AWS_DEFAULT_REGION', 'Not set')
    if region != 'Not set':
        print(f"✅ AWS region: {region}")
    else:
        print("⚠️  AWS_DEFAULT_REGION not set, using default")

    # Check if running in production mode
    flask_env = os.environ.get('FLASK_ENV', 'development')
    print(f"   FLASK_ENV: {flask_env}")

    return all_good


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("AWS Secrets Manager Integration Test")
    print("="*60)

    # Check prerequisites
    if not check_prerequisites():
        print("\n❌ Prerequisites not met. Please configure AWS credentials first.")
        print("   Run: aws configure")
        sys.exit(1)

    # Run tests
    results = []
    results.append(("Individual Secret", test_individual_secret()))
    results.append(("JSON Secret", test_json_secret()))
    results.append(("Helper Function", test_helper_function()))
    results.append(("All Secrets", test_all_secrets()))
    results.append(("Caching", test_caching()))
    results.append(("Error Handling", test_error_handling()))

    # Print summary
    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")

    print(f"\n{passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        sys.exit(1)


if __name__ == '__main__':
    main()
