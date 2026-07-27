"""Regression test: Microsoft Teams ChatOps endpoints had zero authentication.

Found during a scheduled security review: routes/chatops.py's /teams/messages
and /teams/commands accepted any anonymous POST as a legitimate Bot Framework
message — unlike the Slack routes, which verify an HMAC signature when
SLACK_SIGNING_SECRET is configured. Fixed by validating the inbound Bot
Framework JWT (Authorization: Bearer <token>) against Microsoft's JWKS,
checking issuer/audience/expiry, mirroring the joserfc-based pattern already
used for OIDC SSO in services/sso_service.py.
"""
import os

import pytest

os.environ.setdefault('SECRET_KEY', 'test-secret-key')

from routes import chatops  # noqa: E402


def _signed_bot_token(app_id='test-teams-app-id', iss='https://api.botframework.com', kid='k1'):
    from joserfc import jwt
    from joserfc.jwk import RSAKey
    import time

    key = RSAKey.generate_key(2048, parameters={'kid': kid})
    pub_jwks = {'keys': [key.as_dict(private=False)]}
    claims = {
        'iss': iss,
        'aud': app_id,
        'exp': int(time.time()) + 300,
    }
    token = jwt.encode({'alg': 'RS256', 'kid': kid}, claims, key)
    return token, pub_jwks


@pytest.fixture(autouse=True)
def _clear_jwks_cache():
    chatops._TEAMS_JWKS_CACHE.clear()
    yield
    chatops._TEAMS_JWKS_CACHE.clear()


def test_rejects_request_with_no_authorization_header(app, monkeypatch):
    monkeypatch.setenv('TEAMS_APP_ID', 'test-teams-app-id')
    with app.test_request_context('/chatops/teams/messages', method='POST', json={'type': 'message'}):
        assert chatops._verify_teams_request() is False


def test_rejects_when_teams_app_id_not_configured(app, monkeypatch):
    monkeypatch.delenv('TEAMS_APP_ID', raising=False)
    with app.test_request_context(
        '/chatops/teams/messages', method='POST', json={'type': 'message'},
        headers={'Authorization': 'Bearer whatever'},
    ):
        assert chatops._verify_teams_request() is False


def test_rejects_forged_token_wrong_audience(app, monkeypatch):
    monkeypatch.setenv('TEAMS_APP_ID', 'test-teams-app-id')
    token, pub_jwks = _signed_bot_token(app_id='some-other-app-id')
    monkeypatch.setattr(chatops, '_get_botframework_jwks', lambda: pub_jwks)

    with app.test_request_context(
        '/chatops/teams/messages', method='POST', json={'type': 'message'},
        headers={'Authorization': f'Bearer {token}'},
    ):
        assert chatops._verify_teams_request() is False


def test_rejects_forged_token_wrong_issuer(app, monkeypatch):
    monkeypatch.setenv('TEAMS_APP_ID', 'test-teams-app-id')
    token, pub_jwks = _signed_bot_token(iss='https://not-microsoft.example')
    monkeypatch.setattr(chatops, '_get_botframework_jwks', lambda: pub_jwks)

    with app.test_request_context(
        '/chatops/teams/messages', method='POST', json={'type': 'message'},
        headers={'Authorization': f'Bearer {token}'},
    ):
        assert chatops._verify_teams_request() is False


def test_accepts_valid_bot_framework_token(app, monkeypatch):
    monkeypatch.setenv('TEAMS_APP_ID', 'test-teams-app-id')
    token, pub_jwks = _signed_bot_token(app_id='test-teams-app-id')
    monkeypatch.setattr(chatops, '_get_botframework_jwks', lambda: pub_jwks)

    with app.test_request_context(
        '/chatops/teams/messages', method='POST', json={'type': 'message'},
        headers={'Authorization': f'Bearer {token}'},
    ):
        assert chatops._verify_teams_request() is True


def test_teams_messages_route_returns_401_without_valid_token(app, monkeypatch):
    monkeypatch.setenv('TEAMS_APP_ID', 'test-teams-app-id')
    test_client = app.test_client()
    resp = test_client.post('/chatops/teams/messages', json={'type': 'message', 'text': 'status'})
    assert resp.status_code == 401


def test_teams_commands_route_returns_401_without_valid_token(app, monkeypatch):
    monkeypatch.setenv('TEAMS_APP_ID', 'test-teams-app-id')
    test_client = app.test_client()
    resp = test_client.post('/chatops/teams/commands', json={'name': 'status'})
    assert resp.status_code == 401
