#!/usr/bin/env python3
"""
Push local .env secrets to AWS Secrets Manager.

Reads config/.env, extracts sensitive keys, and pushes them as a single JSON
secret named 'devops-agent/production' to AWS Secrets Manager.

Usage:
    python scripts/push_env_to_secrets_manager.py
    python scripts/push_env_to_secrets_manager.py --env-file .env
    python scripts/push_env_to_secrets_manager.py --region us-west-2
"""
import argparse
import json
import os
import sys

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    print("ERROR: boto3 is required. Install with: pip install boto3")
    sys.exit(1)

SECRET_NAME = 'devops-agent/production'

SENSITIVE_KEYS = [
    'ANTHROPIC_API_KEY',
    'SECRET_KEY',
    'DATABASE_URL',
    'AWS_ACCESS_KEY_ID',
    'AWS_SECRET_ACCESS_KEY',
    'STRIPE_SECRET_KEY',
    'STRIPE_WEBHOOK_SECRET',
    'SMTP_USER',
    'SMTP_PASS',
    'CREDENTIAL_ENCRYPTION_KEY',
]


def parse_env_file(path: str) -> dict:
    """Parse a .env file into a dict, ignoring comments and blank lines."""
    values = {}
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                continue
            key, _, value = line.partition('=')
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key in SENSITIVE_KEYS:
                values[key] = value
    return values


def push_secret(secret_data: dict, region: str):
    """Create or update the secret in AWS Secrets Manager (upsert)."""
    client = boto3.client('secretsmanager', region_name=region)
    secret_string = json.dumps(secret_data)

    try:
        client.create_secret(
            Name=SECRET_NAME,
            SecretString=secret_string,
            Description='DevOps Agent production secrets (all sensitive env vars)',
        )
        print(f"Created new secret: {SECRET_NAME}")
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceExistsException':
            client.update_secret(
                SecretId=SECRET_NAME,
                SecretString=secret_string,
                Description='DevOps Agent production secrets (all sensitive env vars)',
            )
            print(f"Updated existing secret: {SECRET_NAME}")
        else:
            raise


def main():
    parser = argparse.ArgumentParser(description='Push .env secrets to AWS Secrets Manager')
    parser.add_argument('--env-file', default='config/.env', help='Path to .env file (default: config/.env)')
    parser.add_argument('--region', default='us-east-1', help='AWS region (default: us-east-1)')
    args = parser.parse_args()

    if not os.path.exists(args.env_file):
        print(f"ERROR: {args.env_file} not found")
        sys.exit(1)

    secrets = parse_env_file(args.env_file)

    if not secrets:
        print(f"ERROR: No sensitive keys found in {args.env_file}")
        print(f"Expected keys: {SENSITIVE_KEYS}")
        sys.exit(1)

    print(f"\nSecrets to push to AWS Secrets Manager ({args.region}):")
    print(f"  Secret name: {SECRET_NAME}")
    print(f"  Source file: {args.env_file}")
    print(f"  Keys found ({len(secrets)}/{len(SENSITIVE_KEYS)}):")
    for key in SENSITIVE_KEYS:
        value = secrets.get(key)
        if value:
            masked = value[:4] + '***' if len(value) > 4 else '***'
            print(f"    {key} = {masked}")
        else:
            print(f"    {key} = (not found)")

    missing = [k for k in SENSITIVE_KEYS if k not in secrets]
    if missing:
        print(f"\n  Warning: {len(missing)} keys not found in .env: {missing}")

    print()
    confirm = input("Push these secrets to AWS Secrets Manager? [y/N] ").strip().lower()
    if confirm != 'y':
        print("Aborted.")
        sys.exit(0)

    push_secret(secrets, args.region)

    print(f"\nDone. Secrets are stored at: {SECRET_NAME} in {args.region}")
    print()
    print("=== IAM Setup Required ===")
    print("Create an IAM policy with the following permissions and attach it")
    print("to your EC2 instance profile / Elastic Beanstalk instance profile:")
    print()
    print(json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": "secretsmanager:GetSecretValue",
            "Resource": f"arn:aws:secretsmanager:{args.region}:*:secret:devops-agent/*"
        }]
    }, indent=2))
    print()
    print("Then set these env vars on the EC2 instance (in .env or systemd):")
    print("  FLASK_ENV=production")
    print("  USE_AWS_SECRETS=true")
    print(f"  AWS_DEFAULT_REGION={args.region}")


if __name__ == '__main__':
    main()
