"""Regression: webhook secrets and events must be visible across separate
`WebhookIntegrationService` instances -- standing in for separate gunicorn
worker processes, which each construct their own instance via
`get_webhook_service()`'s per-process singleton.

Before this fix, `WebhookIntegrationService.__init__` stored `secrets`/
`events` in plain per-instance dict/list attributes. Production runs
multiple gunicorn worker processes, so `POST /webhooks/api/configure` only
ever updated the one worker that handled that request -- every other
worker's `receive_github`/`receive_gitlab` handler then evaluated
`if secret:` as falsy and skipped signature validation entirely, silently
accepting unauthenticated forged webhook payloads whenever a request landed
on one of the unconfigured workers. Found by a 2026-09-14 scheduled audit.
"""
import os
import pytest

os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-webhook-persistence-test')

from services.webhook_integrations import WebhookIntegrationService


@pytest.fixture(autouse=True)
def _cleanup(app):
    yield
    from models import db, WebhookSecret, WebhookEventRecord
    db.session.rollback()
    try:
        WebhookSecret.query.delete()
        WebhookEventRecord.query.delete()
        db.session.commit()
    except Exception:
        db.session.rollback()


def test_secret_set_on_one_instance_is_visible_on_another():
    """Simulates worker A handling /webhooks/api/configure and worker B
    handling a subsequent /webhooks/github -- both must see the same secret."""
    worker_a = WebhookIntegrationService()
    worker_a.set_secret('github', 'my-shared-secret')

    worker_b = WebhookIntegrationService()
    assert worker_b.get_secret('github') == 'my-shared-secret'


def test_unset_secret_is_none_not_a_silent_bypass():
    worker = WebhookIntegrationService()
    assert worker.get_secret('gitlab') is None


def test_secret_update_overwrites_the_persisted_value():
    worker_a = WebhookIntegrationService()
    worker_a.set_secret('github', 'first-secret')
    worker_a.set_secret('github', 'second-secret')

    worker_b = WebhookIntegrationService()
    assert worker_b.get_secret('github') == 'second-secret'


def test_signature_validation_uses_the_persisted_secret_across_instances():
    import hmac
    import hashlib

    worker_a = WebhookIntegrationService()
    worker_a.set_secret('github', 'sig-secret')

    worker_b = WebhookIntegrationService()
    secret = worker_b.get_secret('github')
    payload = b'{"zen": "test"}'
    signature = 'sha256=' + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    assert worker_b.validate_github_signature(payload, signature, secret) is True
    assert worker_b.validate_github_signature(payload, 'sha256=deadbeef', secret) is False


def test_event_processed_on_one_instance_is_visible_on_another():
    worker_a = WebhookIntegrationService()
    event = worker_a.process_webhook('github', 'push', {
        'repository': {'full_name': 'acme/widgets'},
        'ref': 'refs/heads/main',
        'after': 'abc123',
        'pusher': {'name': 'alice'},
        'commits': [{'id': 'abc123def456'}],
    })
    assert event is not None

    worker_b = WebhookIntegrationService()
    events = worker_b.get_events(source='github')
    assert any(e.id == event.id for e in events)


def test_stats_reflect_events_persisted_by_a_different_instance():
    worker_a = WebhookIntegrationService()
    worker_a.process_webhook('gitlab', 'Push Hook', {
        'project': {'path_with_namespace': 'acme/widgets'},
        'ref': 'refs/heads/main',
        'after': 'def456',
        'user_name': 'bob',
        'commits': [],
    })

    worker_b = WebhookIntegrationService()
    stats = worker_b.get_stats()
    assert stats['total_events'] >= 1
    assert stats['by_source'].get('gitlab', 0) >= 1
