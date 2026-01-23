"""
Migrate all secrets from .env file to AWS Secrets Manager
Reads your .env file and uploads everything to AWS Secrets Manager
"""
import boto3
import json
import os
from botocore.exceptions import ClientError
from pathlib import Path


def parse_env_file(env_path='.env'):
    """Parse .env file and extract key-value pairs"""
    secrets = {}

    if not os.path.exists(env_path):
        print(f"Error: {env_path} file not found")
        return None

    print(f"Reading secrets from {env_path}...")

    with open(env_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            # Skip comments and empty lines
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # Parse KEY=VALUE
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()

                # Skip empty values
                if not value:
                    continue

                # Skip AWS profile settings (these are for local use only)
                if key in ['AWS_PROFILE', 'AWS_DEFAULT_REGION']:
                    print(f"  Skipping {key} (local-only setting)")
                    continue

                secrets[key] = value
                print(f"  Found: {key}")

    return secrets


def get_current_secrets_from_aws():
    """Get current secrets from AWS Secrets Manager"""
    sm = boto3.client('secretsmanager', region_name='us-east-1')
    try:
        response = sm.get_secret_value(SecretId='ANTHROPIC_API_KEY')
        return json.loads(response['SecretString'])
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            return {}
        raise


def upload_secrets_to_aws(secrets):
    """Upload secrets to AWS Secrets Manager"""
    sm = boto3.client('secretsmanager', region_name='us-east-1')

    try:
        # Try to update existing secret
        sm.update_secret(
            SecretId='ANTHROPIC_API_KEY',
            SecretString=json.dumps(secrets, indent=2)
        )
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            # Create new secret if it doesn't exist
            try:
                sm.create_secret(
                    Name='ANTHROPIC_API_KEY',
                    Description='DevOps Agent secrets migrated from .env file',
                    SecretString=json.dumps(secrets, indent=2)
                )
                return True
            except ClientError as create_error:
                print(f"Error creating secret: {create_error}")
                return False
        else:
            print(f"Error updating secret: {e}")
            return False


def mask_value(value, show_chars=15):
    """Mask a value for display"""
    if not value:
        return "(empty)"
    value_str = str(value)
    if len(value_str) <= show_chars:
        return "***"
    return value_str[:show_chars] + "..."


def main():
    print("="*70)
    print(" Migrate .env Secrets to AWS Secrets Manager")
    print("="*70)
    print()

    # Step 1: Check AWS credentials
    print("Step 1: Checking AWS credentials...")
    try:
        sts = boto3.client('sts')
        identity = sts.get_caller_identity()
        print(f"  [OK] Connected as: {identity['Arn']}")
    except Exception as e:
        print(f"  [ERROR] AWS credentials not configured: {e}")
        print("  Run: aws configure")
        return

    # Step 2: Parse .env file
    print()
    print("Step 2: Reading .env file...")
    secrets_from_env = parse_env_file('.env')

    if not secrets_from_env:
        print("  [ERROR] No secrets found in .env file")
        return

    print(f"  [OK] Found {len(secrets_from_env)} secret(s)")

    # Step 3: Get current secrets from AWS
    print()
    print("Step 3: Checking current secrets in AWS...")
    try:
        current_aws_secrets = get_current_secrets_from_aws()
        print(f"  [OK] Current AWS has {len(current_aws_secrets)} secret(s)")
    except Exception as e:
        print(f"  [WARNING] Could not retrieve current secrets: {e}")
        current_aws_secrets = {}

    # Step 4: Compare and show what will be updated
    print()
    print("="*70)
    print("Preview: Secrets to Upload")
    print("="*70)
    print()

    # Merge: .env values override AWS values
    merged_secrets = {**current_aws_secrets, **secrets_from_env}

    new_keys = []
    updated_keys = []
    unchanged_keys = []

    for key, value in merged_secrets.items():
        masked = mask_value(value)

        if key not in current_aws_secrets:
            new_keys.append(key)
            print(f"  [NEW] {key}: {masked}")
        elif current_aws_secrets[key] != value:
            updated_keys.append(key)
            old_masked = mask_value(current_aws_secrets[key])
            print(f"  [UPDATE] {key}")
            print(f"           Old: {old_masked}")
            print(f"           New: {masked}")
        else:
            unchanged_keys.append(key)
            print(f"  [SAME] {key}: {masked}")

    # Summary
    print()
    print("="*70)
    print("Summary")
    print("="*70)
    print(f"  New secrets: {len(new_keys)}")
    print(f"  Updated secrets: {len(updated_keys)}")
    print(f"  Unchanged secrets: {len(unchanged_keys)}")
    print(f"  Total secrets: {len(merged_secrets)}")
    print()

    # Show the complete JSON that will be uploaded
    print("Complete JSON to upload:")
    print("-" * 70)
    # Create masked version for display
    masked_json = {}
    for key, value in merged_secrets.items():
        masked_json[key] = mask_value(value, show_chars=20)
    print(json.dumps(masked_json, indent=2))
    print("-" * 70)
    print()

    # Step 5: Confirm upload
    import sys

    # Check for --yes flag
    auto_confirm = '--yes' in sys.argv or '-y' in sys.argv

    if auto_confirm:
        print("Auto-confirming upload (--yes flag provided)")
        confirm = 'yes'
    else:
        try:
            confirm = input("Upload these secrets to AWS Secrets Manager? (yes/no): ").strip().lower()
        except EOFError:
            print("\nNo input detected. Use --yes flag for non-interactive mode.")
            print("Example: python migrate_env_to_secrets.py --yes")
            return

    if confirm not in ['yes', 'y']:
        print()
        print("Migration cancelled.")
        return

    # Step 6: Upload to AWS
    print()
    print("Uploading secrets to AWS Secrets Manager...")

    if upload_secrets_to_aws(merged_secrets):
        print()
        print("="*70)
        print("[SUCCESS] Secrets uploaded successfully!")
        print("="*70)
        print()
        print("Your secrets are now in AWS Secrets Manager:")
        print("  Secret name: ANTHROPIC_API_KEY")
        print("  Region: us-east-1")
        print(f"  Total keys: {len(merged_secrets)}")
        print()
        print("Next steps:")
        print("  1. Test retrieval: python test_secrets_manager.py")
        print("  2. Update app.py: see INTEGRATE_SECRETS_MANAGER.md")
        print("  3. Test locally: python app.py")
        print("  4. Deploy to production")
        print()
        print("IMPORTANT: Keep your .env file for local development")
        print("           The app will use .env in dev mode, AWS in production")
    else:
        print()
        print("[ERROR] Failed to upload secrets")
        print("Check the error messages above")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nMigration cancelled by user")
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {str(e)}")
        import traceback
        traceback.print_exc()
