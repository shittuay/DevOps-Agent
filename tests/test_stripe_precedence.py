"""Regression tests for Stripe config precedence (2026-07-17 rotation outage).

os.environ (populated from AWS Secrets Manager by init_secrets in production)
must win over config/.env. The old file-first order meant a stale config/.env
silently overrode rotated keys in Secrets Manager.
"""
import stripe_integration


def test_env_wins_over_config_file(monkeypatch):
    monkeypatch.setenv('STRIPE_PRICE_STARTER', 'price_from_env')
    monkeypatch.setattr(stripe_integration, '_read_config_env',
                        lambda: {'STRIPE_PRICE_STARTER': 'price_from_file'})
    assert stripe_integration._get_subscription_prices()['starter'] == 'price_from_env'


def test_config_file_is_fallback_when_env_missing(monkeypatch):
    monkeypatch.delenv('STRIPE_PRICE_STARTER', raising=False)
    monkeypatch.setattr(stripe_integration, '_read_config_env',
                        lambda: {'STRIPE_PRICE_STARTER': 'price_from_file'})
    assert stripe_integration._get_subscription_prices()['starter'] == 'price_from_file'


def test_secret_key_prefers_env(monkeypatch):
    monkeypatch.setenv('STRIPE_SECRET_KEY', 'sk_test_env_wins')
    monkeypatch.setattr(stripe_integration, '_read_config_env',
                        lambda: {'STRIPE_SECRET_KEY': 'sk_test_file_loses'})
    stripe_integration._ensure_stripe_configured()
    assert stripe_integration.stripe.api_key == 'sk_test_env_wins'
