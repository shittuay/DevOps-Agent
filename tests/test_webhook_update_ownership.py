"""Regression: update_webhook must enforce ownership, same IDOR class already
fixed for delete_webhook/toggle_webhook/test_webhook/rotate_api_key (see
tests/test_api_key_rotate_ownership.py) — update_webhook was the one sibling
left with no owner check, so it silently repointed/renamed/disabled whatever
webhook_id it was given regardless of caller.
"""
import pytest

from services.api_gateway import APIGatewayService


@pytest.fixture(autouse=True)
def _cleanup(app):
    yield
    from models import db
    db.session.rollback()
    try:
        WebhookEndpoint = APIGatewayService()._get_webhook_model()
        WebhookEndpoint.query.delete()
        db.session.commit()
    except Exception:
        db.session.rollback()


def test_update_rejects_non_owner():
    svc = APIGatewayService()
    webhook = svc.create_webhook(user_id=1, name='k', url='https://example.com/hook', events=['*'])
    assert svc.update_webhook(webhook.id, {'name': 'hijacked'}, user_id=2) is None
    assert svc.get_webhook(webhook.id).name == 'k'


def test_update_owner_succeeds():
    svc = APIGatewayService()
    webhook = svc.create_webhook(user_id=1, name='k', url='https://example.com/hook', events=['*'])
    updated = svc.update_webhook(webhook.id, {'name': 'renamed'}, user_id=1)
    assert updated is not None
    assert updated.name == 'renamed'


def test_update_without_user_id_is_unscoped_for_internal_callers():
    """user_id is optional so trusted internal callers keep working unchanged."""
    svc = APIGatewayService()
    webhook = svc.create_webhook(user_id=1, name='k', url='https://example.com/hook', events=['*'])
    updated = svc.update_webhook(webhook.id, {'name': 'renamed-internally'})
    assert updated is not None
    assert updated.name == 'renamed-internally'
