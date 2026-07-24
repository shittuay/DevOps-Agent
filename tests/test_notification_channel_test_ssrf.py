"""Regression test for a previously-unguarded SSRF gap in
POST /api/notification-channels/<id>/test.

Found while cataloging every raw requests.* call in the codebase to build
the security-invariants checker (tests/test_security_invariants.py): this
route made a raw `requests.post(channel.webhook_url, ...)` call with zero
validation, and echoed the full (untruncated) response body back to the
caller — an SSRF + response-oracle combo that every prior security review
had missed, since channel.webhook_url is user-configured
(UserNotificationChannel) and reachable by any authenticated user testing
their own channel. Fixed by routing through safe_request() and truncating
the echoed body to 500 chars, matching every other webhook-test endpoint.
"""
from unittest.mock import patch

import pytest


@pytest.fixture
def slack_channel(app, test_user, db_session):
    from models import db, UserNotificationChannel

    channel = UserNotificationChannel(
        user_id=test_user.id,
        channel_type='slack',
        name='Test Channel',
        webhook_url='http://169.254.169.254/latest/meta-data/iam/security-credentials/',
        is_active=True,
    )
    db.session.add(channel)
    db.session.commit()

    yield channel

    try:
        c = UserNotificationChannel.query.get(channel.id)
        if c:
            db.session.delete(c)
            db.session.commit()
    except Exception:
        db.session.rollback()


def test_blocks_ssrf_to_metadata_endpoint(authenticated_client, slack_channel):
    response = authenticated_client.post(f'/api/notification-channels/{slack_channel.id}/test')

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is False
    # Never actually connected — the error is the guard rejecting it, not a
    # real (and dangerous) response from the metadata endpoint.
    assert 'disallowed' in data['error'].lower() or 'not allowed' in data['error'].lower()


def test_uses_safe_request_not_raw_requests(app, authenticated_client, test_user, db_session):
    from models import db, UserNotificationChannel

    channel = UserNotificationChannel(
        user_id=test_user.id,
        channel_type='slack',
        name='Safe Channel',
        webhook_url='https://hooks.slack.example/services/T00/B00/xxx',
        is_active=True,
    )
    db.session.add(channel)
    db.session.commit()

    try:
        # test_notification_channel imports safe_request locally inside the
        # view function (from src.utils.network_safety import safe_request),
        # so patch it at the source module — the local import re-reads it
        # fresh on every request.
        with patch('src.utils.network_safety.safe_request') as mock_safe_request:
            mock_safe_request.return_value.status_code = 200
            mock_safe_request.return_value.text = 'ok'
            authenticated_client.post(f'/api/notification-channels/{channel.id}/test')

        mock_safe_request.assert_called_once()
        args, kwargs = mock_safe_request.call_args
        assert args[0] == 'POST'
        assert args[1] == channel.webhook_url
    finally:
        db.session.delete(channel)
        db.session.commit()
