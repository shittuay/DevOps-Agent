"""
AWS Secrets Manager integration for the DevOps Agent
Securely retrieve secrets from AWS Secrets Manager instead of .env files
"""
import boto3
import json
import os
import time
import logging
from botocore.exceptions import ClientError
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# All sensitive keys managed by Secrets Manager
MANAGED_SECRET_KEYS = [
    'ANTHROPIC_API_KEY',
    'SECRET_KEY',
    'DATABASE_URL',
    'AWS_ACCESS_KEY_ID',
    'AWS_SECRET_ACCESS_KEY',
    'STRIPE_SECRET_KEY',
    'STRIPE_PUBLISHABLE_KEY',
    'STRIPE_WEBHOOK_SECRET',
    'STRIPE_PRICE_STARTER',
    'STRIPE_PRICE_PROFESSIONAL',
    'STRIPE_PRICE_BUSINESS',
    'STRIPE_PRICE_PACK_100',
    'STRIPE_PRICE_PACK_250',
    'STRIPE_PRICE_PACK_500',
    'STRIPE_PRICE_PACK_1000',
    'SMTP_USER',
    'SMTP_PASS',
    # Email/SMS delivery config (MFA verification codes, transactional email).
    # SMTP_USER/SMTP_PASS alone are not enough — these companions must load too,
    # otherwise the app falls back to hardcoded defaults (e.g. Brevo's SMTP relay
    # host) and a non-Brevo SMTP credential silently fails to authenticate.
    'EMAIL_PROVIDER',
    'SMTP_HOST',
    'SMTP_PORT',
    'EMAIL_FROM',
    'EMAIL_FROM_NAME',
    'SENDGRID_API_KEY',
    'BREVO_API_KEY',     # required for SMS (phone MFA) and Brevo email
    'SMS_SENDER_NAME',
    'CREDENTIAL_ENCRYPTION_KEY',
    'GROQ_API_KEY',
    'MOONSHOT_API_KEY',
    'BASE_URL',
    'MCP_BASE_URL',
    'MCP_REVIEW_EMAIL',
    'MCP_REVIEW_PASSWORD',
    'MCP_REVIEW_API_KEY',
]

# Primary secret name in AWS Secrets Manager (single JSON blob)
PRIMARY_SECRET_NAME = 'devops-agent/production'
# Legacy fallback secret name
LEGACY_SECRET_NAME = 'ANTHROPIC_API_KEY'


class SecretsManager:
    """Manage secrets from AWS Secrets Manager with TTL-based caching."""

    def __init__(self, region_name: str = "us-east-1", cache_ttl: int = 3600):
        self.region_name = region_name
        self.client = None
        self._cache = {}
        self._cache_timestamps = {}
        self.cache_ttl = cache_ttl

    def _get_client(self):
        """Get or create Secrets Manager client."""
        if self.client is None:
            session = boto3.session.Session()
            self.client = session.client(
                service_name='secretsmanager',
                region_name=self.region_name
            )
        return self.client

    def get_secret(self, secret_name: str, use_cache: bool = True) -> Optional[str]:
        """
        Get a secret from AWS Secrets Manager.

        Args:
            secret_name: Name of the secret in AWS Secrets Manager
            use_cache: Whether to use cached value if available and not expired

        Returns:
            Secret value as string, or None if error

        Raises:
            ClientError: If AWS API call fails
        """
        if use_cache and secret_name in self._cache:
            cached_at = self._cache_timestamps.get(secret_name, 0)
            if time.time() - cached_at < self.cache_ttl:
                return self._cache[secret_name]
            else:
                del self._cache[secret_name]
                del self._cache_timestamps[secret_name]

        try:
            client = self._get_client()
            response = client.get_secret_value(SecretId=secret_name)

            if 'SecretString' in response:
                secret = response['SecretString']
            else:
                import base64
                secret = base64.b64decode(response['SecretBinary'])

            if use_cache:
                self._cache[secret_name] = secret
                self._cache_timestamps[secret_name] = time.time()

            return secret

        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ResourceNotFoundException':
                logger.warning("Secret %s not found in %s", secret_name, self.region_name)
            else:
                logger.error("Error retrieving secret %s: %s", secret_name, e)
            raise

    def get_secret_json(self, secret_name: str, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """Get a JSON secret and parse it."""
        try:
            secret_string = self.get_secret(secret_name, use_cache)
            if secret_string:
                return json.loads(secret_string)
            return None
        except json.JSONDecodeError as e:
            logger.error("Secret %s is not valid JSON: %s", secret_name, e)
            return None

    def get_multiple_secrets(self, secret_names: list) -> Dict[str, str]:
        """Get multiple secrets at once."""
        secrets = {}
        for name in secret_names:
            try:
                secrets[name] = self.get_secret(name)
            except ClientError:
                secrets[name] = None
        return secrets

    def clear_cache(self):
        """Clear the secrets cache and timestamps."""
        self._cache = {}
        self._cache_timestamps = {}


# Singleton instance
_secrets_manager = None


def get_secrets_manager(region_name: str = "us-east-1") -> SecretsManager:
    """Get singleton SecretsManager instance."""
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = SecretsManager(region_name)
    return _secrets_manager


def get_anthropic_api_key() -> Optional[str]:
    """
    Get Anthropic API key from environment or AWS Secrets Manager.

    Returns:
        API key string or None
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if api_key:
        return api_key

    try:
        sm = get_secrets_manager()
        secrets = sm.get_secret_json(PRIMARY_SECRET_NAME)
        if secrets and 'ANTHROPIC_API_KEY' in secrets:
            return secrets['ANTHROPIC_API_KEY']
        # Legacy fallback
        secrets = sm.get_secret_json(LEGACY_SECRET_NAME)
        if secrets and 'ANTHROPIC_API_KEY' in secrets:
            return secrets['ANTHROPIC_API_KEY']
        return sm.get_secret(LEGACY_SECRET_NAME)
    except ClientError:
        return None


def get_moonshot_api_key() -> Optional[str]:
    """
    Get Moonshot (Kimi) API key from environment or AWS Secrets Manager.

    Returns:
        API key string or None
    """
    api_key = os.environ.get('MOONSHOT_API_KEY')
    if api_key:
        return api_key

    try:
        sm = get_secrets_manager()
        secrets = sm.get_secret_json(PRIMARY_SECRET_NAME)
        if secrets and 'MOONSHOT_API_KEY' in secrets:
            return secrets['MOONSHOT_API_KEY']
    except ClientError:
        pass
    return None


def get_all_secrets() -> Dict[str, Optional[str]]:
    """
    Get all application secrets from AWS Secrets Manager.

    Fetches the single JSON secret 'devops-agent/production' containing all keys.
    Falls back to legacy 'ANTHROPIC_API_KEY' secret name.

    Returns:
        Dictionary of secret key -> value
    """
    sm = get_secrets_manager()

    # Try primary consolidated secret
    try:
        secrets = sm.get_secret_json(PRIMARY_SECRET_NAME)
        if secrets:
            logger.info("Loaded secrets from %s", PRIMARY_SECRET_NAME)
            return secrets
    except ClientError:
        logger.warning("Primary secret %s not found, trying legacy", PRIMARY_SECRET_NAME)

    # Fallback to legacy secret name
    try:
        secrets = sm.get_secret_json(LEGACY_SECRET_NAME)
        if secrets:
            logger.info("Loaded secrets from legacy %s", LEGACY_SECRET_NAME)
            return secrets
    except ClientError:
        pass

    return {}


# Records how the current process obtained its secrets. Read by the billing
# diagnostics endpoint so a degraded load is visible without shell access —
# a silent fallback to a stale config/.env key is what made rotated Stripe
# keys look like they "expired" (see CLAUDE_RUNBOOK.md).
_LOAD_STATE: Dict[str, Any] = {
    'source': 'not_initialized',   # secrets_manager | env_fallback | not_initialized | development
    'loaded_count': 0,
    'loaded_at': None,
    'error': None,
}


def get_secrets_state() -> Dict[str, Any]:
    """Return a copy of the current secrets load state (never contains values)."""
    return dict(_LOAD_STATE)


def secrets_are_authoritative() -> bool:
    """True only when this process loaded secrets from AWS Secrets Manager.

    Production code that must not run against a possibly-stale credential
    (Stripe, in particular) should gate on this rather than on the mere
    presence of an env var.
    """
    return _LOAD_STATE.get('source') == 'secrets_manager'


def mark_env_fallback(reason: str) -> None:
    """Record that the process fell back to a local .env file."""
    _LOAD_STATE.update({
        'source': 'env_fallback',
        'loaded_at': time.time(),
        'error': reason,
    })


def init_secrets():
    """
    Initialize secrets for the application.

    In production (FLASK_ENV=production or USE_AWS_SECRETS=true):
      - Loads all secrets from AWS Secrets Manager into os.environ
      - On failure, logs warning and returns False (does NOT crash the app)

    In development:
      - No-op (secrets come from .env via dotenv)

    Returns:
        True if secrets loaded successfully, False otherwise
    """
    flask_env = os.environ.get('FLASK_ENV', 'development')
    use_aws = os.environ.get('USE_AWS_SECRETS', '').lower() == 'true'

    if flask_env != 'production' and not use_aws:
        _LOAD_STATE.update({'source': 'development', 'error': None})
        return False

    logger.info("Loading secrets from AWS Secrets Manager...")
    try:
        secrets = get_all_secrets()
    except Exception as e:
        logger.error(
            "Failed to load secrets from AWS Secrets Manager: %s. "
            "Ensure the EC2 instance has an IAM role with secretsmanager:GetSecretValue permission "
            "on arn:aws:secretsmanager:us-east-1:*:secret:devops-agent/*",
            e
        )
        _LOAD_STATE.update({'source': 'not_initialized', 'error': f'GetSecretValue failed: {e}'})
        return False

    if not secrets:
        logger.error(
            "No secrets returned from AWS Secrets Manager. "
            "Ensure secret '%s' exists in us-east-1 and contains the required keys.",
            PRIMARY_SECRET_NAME
        )
        _LOAD_STATE.update({
            'source': 'not_initialized',
            'error': f"secret '{PRIMARY_SECRET_NAME}' returned no data",
        })
        return False

    loaded = 0
    for key in MANAGED_SECRET_KEYS:
        value = secrets.get(key)
        if value:
            os.environ[key] = value
            loaded += 1

    if loaded == 0:
        logger.error(
            "Secrets JSON was returned but contained none of the expected keys. "
            "Expected keys: %s", MANAGED_SECRET_KEYS
        )
        _LOAD_STATE.update({
            'source': 'not_initialized',
            'error': 'secret JSON contained none of the expected keys',
        })
        return False

    _LOAD_STATE.update({
        'source': 'secrets_manager',
        'loaded_count': loaded,
        'loaded_at': time.time(),
        'error': None,
    })
    logger.info("Loaded %d secrets from AWS Secrets Manager", loaded)
    return True


def reload_secrets() -> Dict[str, Any]:
    """Re-read AWS Secrets Manager into os.environ without restarting the process.

    Rotating a credential previously required a redeploy: init_secrets() runs
    once at startup, so os.environ kept serving the pre-rotation value and the
    new key looked broken. This clears the TTL cache, re-runs init_secrets(),
    and re-points the Stripe SDK at whatever key just landed.

    Returns a state dict; never returns secret values.
    """
    try:
        get_secrets_manager().clear_cache()
    except Exception as e:  # cache clearing must never block a rotation
        logger.warning("Could not clear secrets cache before reload: %s", e)

    ok = init_secrets()

    # Stripe caches the key on the module at import time, so a fresh env var is
    # not enough — re-point the SDK or checkout keeps using the old credential.
    if ok:
        try:
            import stripe
            new_key = os.environ.get('STRIPE_SECRET_KEY')
            if new_key:
                stripe.api_key = new_key
        except Exception as e:
            logger.warning("Secrets reloaded but Stripe SDK re-point failed: %s", e)

    state = get_secrets_state()
    state['reloaded'] = ok
    return state


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    print("Testing AWS Secrets Manager integration...")

    try:
        api_key = get_anthropic_api_key()
        if api_key:
            print(f"Successfully retrieved ANTHROPIC_API_KEY: {api_key[:10]}...")
        else:
            print("Failed to retrieve ANTHROPIC_API_KEY")
    except Exception as e:
        print(f"Error: {e}")
