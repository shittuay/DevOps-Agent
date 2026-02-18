"""Test AWS connection and display available resources."""
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
import os

def test_aws_connection():
    """Test AWS connection and show basic info."""
    print("=" * 70)
    print("AWS Connection Test")
    print("=" * 70)
    print()

    try:
        # Test EC2 connection
        print("[1/4] Testing EC2 connection...")
        ec2 = boto3.client('ec2')
        regions_response = ec2.describe_regions()
        print(f"  [OK] Connected! Found {len(regions_response['Regions'])} AWS regions")

        # Get current region
        session = boto3.session.Session()
        current_region = session.region_name or 'us-east-1'
        print(f"  [OK] Current region: {current_region}")

        # Count EC2 instances
        print(f"\n[2/4] Checking EC2 instances in {current_region}...")
        ec2_resource = boto3.resource('ec2', region_name=current_region)
        instances = list(ec2_resource.instances.all())
        print(f"  [OK] Found {len(instances)} EC2 instance(s)")

        for instance in instances[:5]:  # Show first 5
            state = instance.state['Name']
            name = 'N/A'
            if instance.tags:
                for tag in instance.tags:
                    if tag['Key'] == 'Name':
                        name = tag['Value']
            print(f"    - {instance.id}: {name} ({state})")

        # Count S3 buckets
        print(f"\n[3/4] Checking S3 buckets...")
        s3 = boto3.client('s3')
        buckets = s3.list_buckets()
        print(f"  [OK] Found {len(buckets['Buckets'])} S3 bucket(s)")

        for bucket in buckets['Buckets'][:5]:  # Show first 5
            print(f"    - {bucket['Name']}")

        # Count RDS instances
        print(f"\n[4/4] Checking RDS databases...")
        rds = boto3.client('rds', region_name=current_region)
        databases = rds.describe_db_instances()
        print(f"  [OK] Found {len(databases['DBInstances'])} RDS instance(s)")

        for db in databases['DBInstances'][:5]:  # Show first 5
            print(f"    - {db['DBInstanceIdentifier']} ({db['DBInstanceStatus']})")

        print()
        print("=" * 70)
        print("AWS Connection Successful!")
        print("=" * 70)
        print("=" * 70)
        print()
        print("Next step: Sync your infrastructure in the dashboard")
        print("  1. Visit: http://localhost:5000")
        print("  2. Login to your account")
        print("  3. Go to Dashboard")
        print("  4. Click '🔄 Sync Now'")
        print("  5. Your resources will appear!")
        print()

        return True

    except NoCredentialsError:
        print("  [ERROR] No AWS credentials found")
        print("\nPlease configure AWS credentials:")
        print("  Run: aws configure")
        return False

    except ClientError as e:
        print(f"  [ERROR] AWS Error: {e}")
        return False

    except Exception as e:
        print(f"  [ERROR] Error: {e}")
        return False


if __name__ == '__main__':
    test_aws_connection()
