"""
AWS Secrets Manager integration for the DevOps Agent
Securely retrieve secrets from AWS Secrets Manager instead of .env files
"""
import boto3
import json
import os
from botocore.exceptions import ClientError
from typing import Dict, Any, Optional


class SecretsManager:
    """Manage secrets from AWS Secrets Manager"""

    def __init__(self, region_name: str = "us-east-1"):
        """
        Initialize Secrets Manager client

        Args:
            region_name: AWS region where secrets are stored
        """
        self.region_name = region_name
        self.client = None
        self._cache = {}

    def _get_client(self):
        """Get or create Secrets Manager client"""
        if self.client is None:
            session = boto3.session.Session()
            self.client = session.client(
                service_name='secretsmanager',
                region_name=self.region_name
            )
        return self.client

    def get_secret(self, secret_name: str, use_cache: bool = True) -> Optional[str]:
        """
        Get a secret from AWS Secrets Manager

        Args:
            secret_name: Name of the secret in AWS Secrets Manager
            use_cache: Whether to use cached value if available

        Returns:
            Secret value as string, or None if error

        Raises:
            ClientError: If AWS API call fails
        """
        # Check cache first
        if use_cache and secret_name in self._cache:
            return self._cache[secret_name]

        try:
            client = self._get_client()
            get_secret_value_response = client.get_secret_value(
                SecretId=secret_name
            )

            # Secrets Manager returns either SecretString or SecretBinary
            if 'SecretString' in get_secret_value_response:
                secret = get_secret_value_response['SecretString']
            else:
                # Binary secrets are base64 encoded
                import base64
                secret = base64.b64decode(get_secret_value_response['SecretBinary'])

            # Cache the secret
            if use_cache:
                self._cache[secret_name] = secret

            return secret

        except ClientError as e:
            error_code = e.response['Error']['Code']

            if error_code == 'DecryptionFailureException':
                # Secrets Manager can't decrypt the secret using the KMS key
                print(f"Error: Cannot decrypt secret {secret_name}")
            elif error_code == 'InternalServiceErrorException':
                # An error occurred on the server side
                print(f"Error: Internal server error retrieving {secret_name}")
            elif error_code == 'InvalidParameterException':
                # Invalid parameter in request
                print(f"Error: Invalid parameter for {secret_name}")
            elif error_code == 'InvalidRequestException':
                # Invalid request
                print(f"Error: Invalid request for {secret_name}")
            elif error_code == 'ResourceNotFoundException':
                # Secret not found
                print(f"Error: Secret {secret_name} not found in {self.region_name}")
            else:
                print(f"Error retrieving secret {secret_name}: {str(e)}")

            raise e

    def get_secret_json(self, secret_name: str, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """
        Get a JSON secret from AWS Secrets Manager and parse it

        Args:
            secret_name: Name of the secret in AWS Secrets Manager
            use_cache: Whether to use cached value

        Returns:
            Parsed JSON as dictionary, or None if error
        """
        try:
            secret_string = self.get_secret(secret_name, use_cache)
            if secret_string:
                return json.loads(secret_string)
            return None
        except json.JSONDecodeError as e:
            print(f"Error: Secret {secret_name} is not valid JSON: {str(e)}")
            return None

    def get_multiple_secrets(self, secret_names: list) -> Dict[str, str]:
        """
        Get multiple secrets at once

        Args:
            secret_names: List of secret names

        Returns:
            Dictionary mapping secret names to values
        """
        secrets = {}
        for name in secret_names:
            try:
                secrets[name] = self.get_secret(name)
            except ClientError:
                secrets[name] = None
        return secrets

    def clear_cache(self):
        """Clear the secrets cache"""
        self._cache = {}


# Singleton instance
_secrets_manager = None


def get_secrets_manager(region_name: str = "us-east-1") -> SecretsManager:
    """Get singleton SecretsManager instance"""
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = SecretsManager(region_name)
    return _secrets_manager


def get_anthropic_api_key() -> Optional[str]:
    """
    Get Anthropic API key from AWS Secrets Manager or environment variable

    Returns:
        API key string or None
    """
    # Try environment variable first (for local development)
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if api_key:
        return api_key

    # Try AWS Secrets Manager (for production)
    try:
        sm = get_secrets_manager()
        # Try to get as JSON first (recommended format)
        secrets = sm.get_secret_json('ANTHROPIC_API_KEY')
        if secrets and 'ANTHROPIC_API_KEY' in secrets:
            return secrets['ANTHROPIC_API_KEY']
        # Fall back to plain string
        return sm.get_secret('ANTHROPIC_API_KEY')
    except ClientError:
        return None


def get_all_secrets() -> Dict[str, str]:
    """
    Get all application secrets from AWS Secrets Manager

    This retrieves a single JSON secret that contains all app secrets

    Returns:
        Dictionary of all secrets
    """
    # Try environment variables first (local development)
    if os.environ.get('USE_ENV_SECRETS', 'false').lower() == 'true':
        return {
            'ANTHROPIC_API_KEY': os.environ.get('ANTHROPIC_API_KEY'),
            'SECRET_KEY': os.environ.get('SECRET_KEY'),
            'AWS_ACCESS_KEY_ID': os.environ.get('AWS_ACCESS_KEY_ID'),
            'AWS_SECRET_ACCESS_KEY': os.environ.get('AWS_SECRET_ACCESS_KEY'),
            'STRIPE_SECRET_KEY': os.environ.get('STRIPE_SECRET_KEY'),
            'GITHUB_TOKEN': os.environ.get('GITHUB_TOKEN'),
            'DATABASE_URL': os.environ.get('DATABASE_URL'),
        }

    # Try AWS Secrets Manager (production)
    try:
        sm = get_secrets_manager()
        # Use the actual secret name (adjust based on your setup)
        # Try "ANTHROPIC_API_KEY" first (your current setup)
        secrets = sm.get_secret_json('ANTHROPIC_API_KEY')
        if secrets:
            return secrets
        # Fall back to "devops-agent/secrets" if that exists
        secrets = sm.get_secret_json('devops-agent/secrets')
        return secrets or {}
    except ClientError:
        return {}


def init_secrets():
    """
    Initialize secrets for the application
    Sets environment variables from AWS Secrets Manager
    """
    secrets = get_all_secrets()

    for key, value in secrets.items():
        if value:
            os.environ[key] = value
            print(f"✓ Loaded secret: {key}")


if __name__ == '__main__':
    # Test the secrets manager
    print("Testing AWS Secrets Manager integration...")

    try:
        api_key = get_anthropic_api_key()
        if api_key:
            print(f"✅ Successfully retrieved ANTHROPIC_API_KEY: {api_key[:10]}...")
        else:
            print("❌ Failed to retrieve ANTHROPIC_API_KEY")
    except Exception as e:
        print(f"❌ Error: {str(e)}")
