"""Guards against silently paying with a stale Stripe key.

The failure these lock down: AWS Secrets Manager fails, the app falls back to a
local config/.env holding a PRE-ROTATION key, Stripe answers every call with a
plain 401, and from the outside it looks like the key "expired" again. The fix
is to refuse the fallback on the money path in production and say why.
"""

import os

import pytest

import services.secrets_manager as sm


@pytest.fixture
def restore_secret_state():
    """Snapshot and restore module + env state touched by these tests."""
    original = dict(sm._LOAD_STATE)
    saved_env = {
        k: os.environ.get(k)
        for k in ('FLASK_ENV', 'USE_AWS_SECRETS', 'STRIPE_SECRET_KEY')
    }
    yield
    sm._LOAD_STATE.clear()
    sm._LOAD_STATE.update(original)
    for k, v in saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


class TestSecretsState:
    def test_state_reports_source_after_fallback(self, restore_secret_state):
        sm.mark_env_fallback('Secrets Manager unavailable; loaded config/.env')

        state = sm.get_secrets_state()
        assert state['source'] == 'env_fallback'
        assert 'config/.env' in state['error']
        assert sm.secrets_are_authoritative() is False

    def test_authoritative_only_when_loaded_from_secrets_manager(self, restore_secret_state):
        sm._LOAD_STATE.update({'source': 'secrets_manager', 'error': None})
        assert sm.secrets_are_authoritative() is True

        for source in ('env_fallback', 'not_initialized', 'development'):
            sm._LOAD_STATE.update({'source': source})
            assert sm.secrets_are_authoritative() is False, source

    def test_state_copy_is_not_live(self, restore_secret_state):
        """Callers must not be able to mutate load state through the getter."""
        sm._LOAD_STATE.update({'source': 'secrets_manager'})
        state = sm.get_secrets_state()
        state['source'] = 'tampered'
        assert sm.get_secrets_state()['source'] == 'secrets_manager'

    def test_state_never_carries_secret_values(self, restore_secret_state):
        sm.mark_env_fallback('Secrets Manager unavailable; loaded config/.env')
        serialized = str(sm.get_secrets_state())
        assert 'sk_live' not in serialized
        assert 'sk_test' not in serialized


class TestStripeConfigGuard:
    def test_production_refuses_stale_fallback_key(self, restore_secret_state):
        """The core regression: a fallback key must never reach Stripe in prod."""
        from stripe_integration import _ensure_stripe_configured

        os.environ['FLASK_ENV'] = 'production'
        os.environ['STRIPE_SECRET_KEY'] = 'sk_live_stale_rotated_key'
        sm.mark_env_fallback('Secrets Manager unavailable; loaded config/.env')

        with pytest.raises(RuntimeError) as exc:
            _ensure_stripe_configured()

        msg = str(exc.value)
        assert 'possibly-stale' in msg
        # The error must say how to recover without a redeploy.
        assert '/admin/api/secrets/reload' in msg

    def test_production_accepts_key_from_secrets_manager(self, restore_secret_state):
        import stripe
        from stripe_integration import _ensure_stripe_configured

        os.environ['FLASK_ENV'] = 'production'
        os.environ['STRIPE_SECRET_KEY'] = 'sk_live_authoritative'
        sm._LOAD_STATE.update({'source': 'secrets_manager', 'error': None})

        _ensure_stripe_configured()
        assert stripe.api_key == 'sk_live_authoritative'

    def test_production_missing_key_names_the_secret(self, restore_secret_state):
        from stripe_integration import _ensure_stripe_configured

        os.environ['FLASK_ENV'] = 'production'
        os.environ.pop('STRIPE_SECRET_KEY', None)
        sm._LOAD_STATE.update({'source': 'secrets_manager', 'error': None})

        with pytest.raises(RuntimeError) as exc:
            _ensure_stripe_configured()
        assert 'devops-agent/production' in str(exc.value)

    def test_use_aws_secrets_flag_also_triggers_production_rules(self, restore_secret_state):
        """USE_AWS_SECRETS=true is a production posture even without FLASK_ENV."""
        from stripe_integration import _ensure_stripe_configured

        os.environ.pop('FLASK_ENV', None)
        os.environ['USE_AWS_SECRETS'] = 'true'
        os.environ['STRIPE_SECRET_KEY'] = 'sk_live_stale'
        sm.mark_env_fallback('Secrets Manager unavailable')

        with pytest.raises(RuntimeError):
            _ensure_stripe_configured()

    def test_development_still_allows_local_env_key(self, restore_secret_state):
        """Local dev must keep working without any AWS access at all."""
        import stripe
        from stripe_integration import _ensure_stripe_configured

        os.environ.pop('FLASK_ENV', None)
        os.environ.pop('USE_AWS_SECRETS', None)
        os.environ['STRIPE_SECRET_KEY'] = 'sk_test_local_dev'

        _ensure_stripe_configured()
        assert stripe.api_key == 'sk_test_local_dev'
