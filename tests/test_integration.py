#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test script for DevOps Agent integration testing.
Tests GCP, Azure, and AWS tools integration.
"""
import sys
import os

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_imports():
    """Test that all modules can be imported."""
    print("=" * 60)
    print("Testing Module Imports")
    print("=" * 60)

    try:
        from src.config import ConfigManager
        print("✓ ConfigManager imported successfully")
    except Exception as e:
        print(f"✗ ConfigManager import failed: {e}")
        return False

    try:
        from src.tools import aws_tools
        print("✓ AWS tools imported successfully")
    except Exception as e:
        print(f"✗ AWS tools import failed: {e}")
        return False

    try:
        from src.tools import azure_tools
        print("✓ Azure tools imported successfully")
    except Exception as e:
        print(f"✗ Azure tools import failed: {e}")
        return False

    try:
        from src.tools import gcp_tools
        print("✓ GCP tools imported successfully")
    except Exception as e:
        print(f"✗ GCP tools import failed: {e}")
        return False

    print()
    return True


def test_tool_counts():
    """Test tool counts for each cloud provider."""
    print("=" * 60)
    print("Testing Tool Counts")
    print("=" * 60)

    try:
        from src.tools import aws_tools, azure_tools, gcp_tools

        aws_count = len(aws_tools.get_tools())
        print(f"✓ AWS tools: {aws_count} tools available")

        azure_count = len(azure_tools.get_tools())
        print(f"✓ Azure tools: {azure_count} tools available")

        gcp_count = len(gcp_tools.get_tools())
        print(f"✓ GCP tools: {gcp_count} tools available")

        total = aws_count + azure_count + gcp_count
        print(f"\n  Total cloud tools: {total}")

        # Verify expected counts
        if gcp_count < 20:
            print(f"⚠ Warning: Expected at least 20 GCP tools, found {gcp_count}")

        print()
        return True

    except Exception as e:
        print(f"✗ Tool count test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_gcp_tool_names():
    """Test that all expected GCP tools are present."""
    print("=" * 60)
    print("Testing GCP Tool Names")
    print("=" * 60)

    expected_tools = [
        'list_compute_instances',
        'manage_compute_instance',
        'create_compute_instance',
        'delete_compute_instance',
        'list_storage_buckets',
        'create_storage_bucket',
        'delete_storage_bucket',
        'list_gke_clusters',
        'list_cloud_sql_instances',
        'create_cloud_sql_instance',
        'get_gcp_metrics',
        'list_cloud_functions',
        'list_cloud_run_services',
        'list_pubsub_topics',
        'publish_pubsub_message',
        'list_bigquery_datasets',
        'query_bigquery',
        'list_secrets',
        'get_secret_value',
        'list_cloud_logs'
    ]

    try:
        from src.tools import gcp_tools
        tools = gcp_tools.get_tools()
        tool_names = [tool['name'] for tool in tools]

        missing_tools = []
        for expected in expected_tools:
            if expected in tool_names:
                print(f"✓ {expected}")
            else:
                print(f"✗ {expected} - MISSING!")
                missing_tools.append(expected)

        if missing_tools:
            print(f"\n⚠ Missing {len(missing_tools)} tools: {missing_tools}")
            return False
        else:
            print(f"\n✓ All {len(expected_tools)} expected GCP tools are present!")

        print()
        return True

    except Exception as e:
        print(f"✗ GCP tool name test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_config_properties():
    """Test that config manager has GCP and Azure properties."""
    print("=" * 60)
    print("Testing Config Properties")
    print("=" * 60)

    # Create a temporary .env file for testing
    test_env_content = """
ANTHROPIC_API_KEY=test_key_placeholder
GCP_PROJECT_ID=test-project
AZURE_SUBSCRIPTION_ID=test-subscription
"""

    try:
        # Write test .env
        with open('.env.test', 'w') as f:
            f.write(test_env_content)

        from src.config import ConfigManager
        config = ConfigManager(env_path='.env.test')

        # Test GCP properties
        print("GCP Config Properties:")
        print(f"  ✓ gcp_enabled: {config.gcp_enabled}")
        print(f"  ✓ gcp_project_id: {config.gcp_project_id}")
        print(f"  ✓ gcp_default_region: {config.gcp_default_region}")
        print(f"  ✓ gcp_default_zone: {config.gcp_default_zone}")

        # Test Azure properties
        print("\nAzure Config Properties:")
        print(f"  ✓ azure_enabled: {config.azure_enabled}")
        print(f"  ✓ azure_subscription_id: {config.azure_subscription_id}")
        print(f"  ✓ azure_default_location: {config.azure_default_location}")

        print()
        return True

    except Exception as e:
        print(f"✗ Config property test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Clean up test .env
        if os.path.exists('.env.test'):
            os.remove('.env.test')


def test_tool_schemas():
    """Test that tool schemas are valid."""
    print("=" * 60)
    print("Testing Tool Schemas")
    print("=" * 60)

    try:
        from src.tools import gcp_tools
        tools = gcp_tools.get_tools()

        errors = []
        for tool in tools:
            # Check required fields
            if 'name' not in tool:
                errors.append(f"Tool missing 'name' field")
            if 'description' not in tool:
                errors.append(f"Tool {tool.get('name', 'unknown')} missing 'description'")
            if 'input_schema' not in tool:
                errors.append(f"Tool {tool.get('name', 'unknown')} missing 'input_schema'")
            if 'handler' not in tool:
                errors.append(f"Tool {tool.get('name', 'unknown')} missing 'handler'")

            # Check that handler is callable
            if 'handler' in tool and not callable(tool['handler']):
                errors.append(f"Tool {tool.get('name', 'unknown')} handler is not callable")

        if errors:
            print("✗ Schema validation errors:")
            for error in errors:
                print(f"  - {error}")
            return False
        else:
            print(f"✓ All {len(tools)} GCP tool schemas are valid")
            print()
            return True

    except Exception as e:
        print(f"✗ Tool schema test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("DevOps Agent Integration Test Suite")
    print("=" * 60 + "\n")

    results = []

    # Run tests
    results.append(("Module Imports", test_imports()))
    results.append(("Tool Counts", test_tool_counts()))
    results.append(("GCP Tool Names", test_gcp_tool_names()))
    results.append(("Config Properties", test_config_properties()))
    results.append(("Tool Schemas", test_tool_schemas()))

    # Summary
    print("=" * 60)
    print("Test Summary")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"{test_name}: {status}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed! Integration is working correctly.")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Please review the errors above.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
