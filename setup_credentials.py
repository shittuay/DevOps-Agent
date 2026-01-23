"""
Interactive credential setup for DevOps Agent.
Helps you configure credentials securely.
"""
import os
import sys
import secrets
from pathlib import Path


def print_header(text):
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(text)
    print("=" * 70 + "\n")


def print_step(number, text):
    """Print a step number."""
    print(f"\n[{number}] {text}")


def get_input(prompt, required=False, secret=False):
    """Get user input with validation."""
    while True:
        if secret:
            import getpass
            value = getpass.getpass(prompt + ": ")
        else:
            value = input(prompt + ": ").strip()

        if not value and required:
            print("  This field is required. Please provide a value.")
            continue

        if not value:
            return None

        return value


def main():
    """Interactive credential setup."""
    print_header("DevOps Agent - Credential Setup Wizard")

    print("This wizard will help you set up credentials for your DevOps Agent.")
    print("Your credentials will be stored securely in a .env file.")
    print("\nPress Ctrl+C at any time to cancel.\n")

    # Check if .env already exists
    env_file = Path(".env")
    if env_file.exists():
        print("⚠️  WARNING: .env file already exists!")
        overwrite = input("Do you want to overwrite it? (yes/no): ").lower()
        if overwrite != 'yes':
            print("\nSetup cancelled. Your existing .env file was not modified.")
            return

    credentials = {}

    # Required credentials
    print_header("Step 1: Required Credentials")

    print_step(1, "Anthropic API Key")
    print("  Get your API key from: https://console.anthropic.com/")
    print("  This is required for AI-powered automation.\n")
    anthropic_key = get_input("Enter your Anthropic API Key", required=True, secret=True)
    credentials['ANTHROPIC_API_KEY'] = anthropic_key

    print_step(2, "Flask Secret Key")
    print("  Generating a secure random secret key...")
    secret_key = secrets.token_hex(32)
    print(f"  ✓ Generated: {secret_key[:16]}... (shown partially for security)")
    credentials['SECRET_KEY'] = secret_key

    # Database URL
    credentials['DATABASE_URL'] = 'sqlite:///devops_agent.db'

    # Optional cloud providers
    print_header("Step 2: Cloud Provider Credentials (Optional)")
    print("Configure the cloud providers you use. Press Enter to skip.\n")

    # AWS
    print_step(1, "AWS Credentials")
    print("  Get from: AWS Console → IAM → Users → Create User")
    aws_setup = input("  Configure AWS? (yes/no) [no]: ").lower() == 'yes'

    if aws_setup:
        aws_key = get_input("  AWS Access Key ID", secret=True)
        aws_secret = get_input("  AWS Secret Access Key", secret=True)
        aws_region = get_input("  AWS Default Region", required=False) or "us-east-1"

        if aws_key and aws_secret:
            credentials['AWS_ACCESS_KEY_ID'] = aws_key
            credentials['AWS_SECRET_ACCESS_KEY'] = aws_secret
            credentials['AWS_DEFAULT_REGION'] = aws_region
            print("  ✓ AWS credentials configured")

    # GCP
    print("\n" + "-" * 70)
    print_step(2, "Google Cloud Platform")
    print("  Get from: GCP Console → IAM → Service Accounts → Create Key")
    gcp_setup = input("  Configure GCP? (yes/no) [no]: ").lower() == 'yes'

    if gcp_setup:
        gcp_creds = get_input("  Path to GCP service account JSON file")
        gcp_project = get_input("  GCP Project ID")

        if gcp_creds and gcp_project:
            credentials['GOOGLE_APPLICATION_CREDENTIALS'] = gcp_creds
            credentials['GCP_PROJECT_ID'] = gcp_project
            print("  ✓ GCP credentials configured")

    # Azure
    print("\n" + "-" * 70)
    print_step(3, "Microsoft Azure")
    print("  Get from: Azure Portal → App Registrations → Service Principal")
    azure_setup = input("  Configure Azure? (yes/no) [no]: ").lower() == 'yes'

    if azure_setup:
        azure_client_id = get_input("  Azure Client ID", secret=True)
        azure_client_secret = get_input("  Azure Client Secret", secret=True)
        azure_tenant_id = get_input("  Azure Tenant ID", secret=True)
        azure_subscription_id = get_input("  Azure Subscription ID", secret=True)

        if all([azure_client_id, azure_client_secret, azure_tenant_id, azure_subscription_id]):
            credentials['AZURE_CLIENT_ID'] = azure_client_id
            credentials['AZURE_CLIENT_SECRET'] = azure_client_secret
            credentials['AZURE_TENANT_ID'] = azure_tenant_id
            credentials['AZURE_SUBSCRIPTION_ID'] = azure_subscription_id
            print("  ✓ Azure credentials configured")

    # GitHub
    print_header("Step 3: CI/CD Integration (Optional)")

    print_step(1, "GitHub")
    print("  Get from: GitHub → Settings → Developer settings → Personal tokens")
    github_setup = input("  Configure GitHub? (yes/no) [no]: ").lower() == 'yes'

    if github_setup:
        github_token = get_input("  GitHub Personal Access Token", secret=True)
        if github_token:
            credentials['GITHUB_TOKEN'] = github_token
            print("  ✓ GitHub credentials configured")

    # Stripe (optional)
    print_header("Step 4: Payment Processing (Optional)")
    print("Only needed if you want to accept payments in your app.\n")

    stripe_setup = input("Configure Stripe? (yes/no) [no]: ").lower() == 'yes'

    if stripe_setup:
        print("  Get from: https://dashboard.stripe.com/apikeys")
        stripe_publishable = get_input("  Stripe Publishable Key")
        stripe_secret = get_input("  Stripe Secret Key", secret=True)
        stripe_webhook = get_input("  Stripe Webhook Secret", secret=True)

        if stripe_publishable and stripe_secret:
            credentials['STRIPE_PUBLISHABLE_KEY'] = stripe_publishable
            credentials['STRIPE_SECRET_KEY'] = stripe_secret
            if stripe_webhook:
                credentials['STRIPE_WEBHOOK_SECRET'] = stripe_webhook
            print("  ✓ Stripe credentials configured")

    # Write .env file
    print_header("Step 5: Saving Credentials")

    try:
        with open('.env', 'w') as f:
            f.write("# DevOps Agent - Environment Configuration\n")
            f.write("# Generated by setup wizard\n")
            f.write(f"# Created: {__import__('datetime').datetime.now().isoformat()}\n\n")

            f.write("# REQUIRED\n")
            f.write(f"ANTHROPIC_API_KEY={credentials['ANTHROPIC_API_KEY']}\n")
            f.write(f"SECRET_KEY={credentials['SECRET_KEY']}\n")
            f.write(f"DATABASE_URL={credentials['DATABASE_URL']}\n\n")

            if any(key.startswith('AWS_') for key in credentials):
                f.write("# AWS\n")
                if 'AWS_ACCESS_KEY_ID' in credentials:
                    f.write(f"AWS_ACCESS_KEY_ID={credentials['AWS_ACCESS_KEY_ID']}\n")
                if 'AWS_SECRET_ACCESS_KEY' in credentials:
                    f.write(f"AWS_SECRET_ACCESS_KEY={credentials['AWS_SECRET_ACCESS_KEY']}\n")
                if 'AWS_DEFAULT_REGION' in credentials:
                    f.write(f"AWS_DEFAULT_REGION={credentials['AWS_DEFAULT_REGION']}\n")
                f.write("\n")

            if 'GOOGLE_APPLICATION_CREDENTIALS' in credentials:
                f.write("# GCP\n")
                f.write(f"GOOGLE_APPLICATION_CREDENTIALS={credentials['GOOGLE_APPLICATION_CREDENTIALS']}\n")
                f.write(f"GCP_PROJECT_ID={credentials['GCP_PROJECT_ID']}\n\n")

            if any(key.startswith('AZURE_') for key in credentials):
                f.write("# Azure\n")
                for key in ['AZURE_CLIENT_ID', 'AZURE_CLIENT_SECRET', 'AZURE_TENANT_ID', 'AZURE_SUBSCRIPTION_ID']:
                    if key in credentials:
                        f.write(f"{key}={credentials[key]}\n")
                f.write("\n")

            if 'GITHUB_TOKEN' in credentials:
                f.write("# GitHub\n")
                f.write(f"GITHUB_TOKEN={credentials['GITHUB_TOKEN']}\n\n")

            if any(key.startswith('STRIPE_') for key in credentials):
                f.write("# Stripe\n")
                for key in ['STRIPE_PUBLISHABLE_KEY', 'STRIPE_SECRET_KEY', 'STRIPE_WEBHOOK_SECRET']:
                    if key in credentials:
                        f.write(f"{key}={credentials[key]}\n")
                f.write("\n")

        print("✓ Credentials saved to .env file")
        print("\nSecurity reminder:")
        print("  - .env file contains sensitive credentials")
        print("  - Never commit .env to version control")
        print("  - Keep it secure and backed up safely")

    except Exception as e:
        print(f"✗ Error saving credentials: {e}")
        return 1

    # Add .env to .gitignore if needed
    gitignore_file = Path(".gitignore")
    if gitignore_file.exists():
        with open('.gitignore', 'r') as f:
            if '.env' not in f.read():
                with open('.gitignore', 'a') as f:
                    f.write("\n# Environment variables\n.env\n")
                print("✓ Added .env to .gitignore")
    else:
        with open('.gitignore', 'w') as f:
            f.write("# Environment variables\n.env\n")
        print("✓ Created .gitignore with .env entry")

    # Summary
    print_header("Setup Complete!")

    print("✓ Credentials configured and saved securely")
    print("\nConfigured services:")
    if any(key.startswith('AWS_') for key in credentials):
        print("  ✓ AWS")
    if 'GOOGLE_APPLICATION_CREDENTIALS' in credentials:
        print("  ✓ Google Cloud Platform")
    if any(key.startswith('AZURE_') for key in credentials):
        print("  ✓ Microsoft Azure")
    if 'GITHUB_TOKEN' in credentials:
        print("  ✓ GitHub")
    if any(key.startswith('STRIPE_') for key in credentials):
        print("  ✓ Stripe Payments")

    print("\nNext steps:")
    print("  1. Restart Flask server: python app.py")
    print("  2. Visit: http://localhost:5000")
    print("  3. Go to Dashboard → Click 'Sync Now'")
    print("  4. Your infrastructure should appear!")

    print("\nNeed more help?")
    print("  - Read: CREDENTIALS_SETUP_GUIDE.md")
    print("  - Check: .env.example for all available options")

    print("\n" + "=" * 70)
    print("Your DevOps Agent is ready to save you time and money! 🚀")
    print("=" * 70 + "\n")

    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nSetup cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nError: {e}")
        sys.exit(1)
