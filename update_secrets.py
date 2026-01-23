"""
Helper script to update secrets in AWS Secrets Manager
Adds or updates secrets in your ANTHROPIC_API_KEY JSON secret
"""
import boto3
import json
import secrets
from botocore.exceptions import ClientError


def get_current_secrets():
    """Get current secrets from AWS Secrets Manager"""
    sm = boto3.client('secretsmanager', region_name='us-east-1')
    try:
        response = sm.get_secret_value(SecretId='ANTHROPIC_API_KEY')
        return json.loads(response['SecretString'])
    except ClientError as e:
        print(f"Error retrieving current secrets: {e}")
        return {}


def update_secrets(new_secrets):
    """Update secrets in AWS Secrets Manager"""
    sm = boto3.client('secretsmanager', region_name='us-east-1')
    try:
        sm.update_secret(
            SecretId='ANTHROPIC_API_KEY',
            SecretString=json.dumps(new_secrets, indent=2)
        )
        return True
    except ClientError as e:
        print(f"Error updating secrets: {e}")
        return False


def generate_secret_key():
    """Generate a secure random secret key"""
    return secrets.token_hex(32)


def main():
    print("="*70)
    print(" AWS Secrets Manager - Update Secrets")
    print("="*70)
    print()
    print("This script will help you add secrets to your AWS Secrets Manager.")
    print("Current secret name: ANTHROPIC_API_KEY (JSON format)")
    print()

    # Get current secrets
    print("Fetching current secrets...")
    current_secrets = get_current_secrets()

    if not current_secrets:
        print("Error: Could not retrieve current secrets")
        return

    print(f"Found {len(current_secrets)} existing key(s):")
    for key in current_secrets.keys():
        value = current_secrets[key]
        masked = str(value)[:15] + "..." if value and len(str(value)) > 15 else "***"
        print(f"  - {key}: {masked}")

    print()
    print("="*70)
    print("Add/Update Secrets")
    print("="*70)
    print()

    # Ask what to do
    print("What would you like to do?")
    print("1. Add all required secrets (recommended)")
    print("2. Add/update a single secret")
    print("3. Generate a new SECRET_KEY")
    print("4. View current secrets (masked)")
    print("5. Exit")
    print()

    choice = input("Enter your choice (1-5): ").strip()

    if choice == '1':
        # Add all required secrets
        print()
        print("Adding all required secrets...")
        print("Leave blank to keep existing value or skip")
        print()

        # SECRET_KEY
        if 'SECRET_KEY' not in current_secrets or not current_secrets.get('SECRET_KEY'):
            print("SECRET_KEY not found. Generating a secure random key...")
            current_secrets['SECRET_KEY'] = generate_secret_key()
            print(f"  Generated: {current_secrets['SECRET_KEY'][:20]}...")
        else:
            response = input(f"SECRET_KEY exists. Generate new? (y/N): ").strip().lower()
            if response == 'y':
                current_secrets['SECRET_KEY'] = generate_secret_key()
                print(f"  Generated: {current_secrets['SECRET_KEY'][:20]}...")

        # STRIPE_SECRET_KEY
        value = input("STRIPE_SECRET_KEY (or press Enter to skip): ").strip()
        if value:
            current_secrets['STRIPE_SECRET_KEY'] = value

        # STRIPE_PUBLISHABLE_KEY
        value = input("STRIPE_PUBLISHABLE_KEY (or press Enter to skip): ").strip()
        if value:
            current_secrets['STRIPE_PUBLISHABLE_KEY'] = value

        # DATABASE_URL
        if 'DATABASE_URL' not in current_secrets:
            current_secrets['DATABASE_URL'] = 'sqlite:///instance/devops.db'
            print("  Set DATABASE_URL to: sqlite:///instance/devops.db")
        else:
            value = input(f"DATABASE_URL (current: {current_secrets['DATABASE_URL'][:30]}..., press Enter to keep): ").strip()
            if value:
                current_secrets['DATABASE_URL'] = value

        # GITHUB_TOKEN
        value = input("GITHUB_TOKEN (optional, press Enter to skip): ").strip()
        if value:
            current_secrets['GITHUB_TOKEN'] = value

        print()
        print("Preview of secrets to be saved:")
        for key, val in current_secrets.items():
            masked = str(val)[:20] + "..." if val and len(str(val)) > 20 else "***"
            print(f"  - {key}: {masked}")

        print()
        confirm = input("Save these secrets to AWS Secrets Manager? (y/N): ").strip().lower()
        if confirm == 'y':
            if update_secrets(current_secrets):
                print()
                print("[SUCCESS] Secrets updated successfully!")
                print()
                print("Next steps:")
                print("1. Test: python test_secrets_manager.py")
                print("2. Update app.py: see INTEGRATE_SECRETS_MANAGER.md")
            else:
                print("[ERROR] Failed to update secrets")
        else:
            print("Cancelled.")

    elif choice == '2':
        # Add/update single secret
        print()
        key = input("Secret key name: ").strip()
        if not key:
            print("Invalid key name")
            return

        value = input(f"Secret value for {key}: ").strip()
        if not value:
            print("Invalid value")
            return

        current_secrets[key] = value

        print()
        confirm = input(f"Update {key} in AWS Secrets Manager? (y/N): ").strip().lower()
        if confirm == 'y':
            if update_secrets(current_secrets):
                print("[SUCCESS] Secret updated successfully!")
            else:
                print("[ERROR] Failed to update secret")
        else:
            print("Cancelled.")

    elif choice == '3':
        # Generate SECRET_KEY
        new_key = generate_secret_key()
        print()
        print("Generated SECRET_KEY:")
        print(f"  {new_key}")
        print()
        save = input("Save this to AWS Secrets Manager? (y/N): ").strip().lower()
        if save == 'y':
            current_secrets['SECRET_KEY'] = new_key
            if update_secrets(current_secrets):
                print("[SUCCESS] SECRET_KEY updated!")
            else:
                print("[ERROR] Failed to update")

    elif choice == '4':
        # View current secrets
        print()
        print("Current secrets (masked):")
        for key, value in current_secrets.items():
            masked = str(value)[:20] + "..." if value and len(str(value)) > 20 else "***"
            print(f"  {key}: {masked}")

    elif choice == '5':
        print("Exiting...")
        return

    else:
        print("Invalid choice")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled by user")
    except Exception as e:
        print(f"\nError: {str(e)}")
