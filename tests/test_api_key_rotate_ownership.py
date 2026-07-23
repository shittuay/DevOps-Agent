"""Regression: rotate_api_key must enforce ownership (same IDOR class as the
webhook delete/toggle/test bug) and must not crash calling the owner-scoped
revoke_api_key.
"""
import pytest

from services.api_gateway import APIGatewayService


@pytest.fixture(autouse=True)
def _cleanup(app):
    yield
    from models import db, APIKey
    db.session.rollback()
    try:
        APIKey.query.delete()
        db.session.commit()
    except Exception:
        db.session.rollback()


def test_rotate_rejects_non_owner(app, db_session):
    svc = APIGatewayService()
    _key, _plain = svc.create_api_key(user_id=1, name='k', scopes=['read'])
    # A different user may not rotate it.
    assert svc.rotate_api_key(_key.id, user_id=2) is None


def test_rotate_owner_succeeds_and_revokes_old(app, db_session):
    from models import APIKey
    svc = APIGatewayService()
    old, _plain = svc.create_api_key(user_id=1, name='k', scopes=['read'])
    old_id = old.id

    result = svc.rotate_api_key(old_id, user_id=1)
    assert result is not None            # did not crash on the revoke call
    new_key, plain = result
    assert new_key.user_id == 1
    # Old key is revoked, new key is active.
    assert APIKey.query.get(old_id).is_active is False
    assert new_key.is_active is True
