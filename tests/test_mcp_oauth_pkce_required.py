"""MCP OAuth must require PKCE (S256) for every client (2026-11-12 daily review).

/authorize used to issue a code with no code_challenge, and /token only checked
the verifier when a challenge had been stored, so such a code could be redeemed
by anyone holding it with any non-empty code_verifier. The built-in client's
secret is published, so it is treated the same as a public client.
"""
import base64
import hashlib
import secrets
from datetime import timedelta

import pytest

from routes.mcp import OAUTH_CLIENT_ID
from src.utils.timeutils import utcnow

CALLBACK = 'https://claude.ai/api/mcp/auth_callback'


def _pkce_pair():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    return verifier, challenge


def _client_id(client):
    reg = client.post('/mcp/oauth/register', json={'client_name': 'pkce-test', 'redirect_uris': [CALLBACK]})
    return reg.get_json()['client_id']


@pytest.fixture
def cleanup_tokens(test_user):
    yield
    from models import MCPOAuthCode, MCPOAuthToken, db
    MCPOAuthToken.query.filter_by(user_id=test_user.id).delete()
    MCPOAuthCode.query.filter_by(user_id=test_user.id).delete()
    db.session.commit()


@pytest.mark.parametrize('extra', [
    {},                                                         # no challenge at all
    {'code_challenge': 'a' * 43, 'code_challenge_method': 'plain'},
    {'code_challenge': 'short', 'code_challenge_method': 'S256'},
    {'code_challenge': 'a' * 42 + '=', 'code_challenge_method': 'S256'},
])
@pytest.mark.parametrize('builtin', [False, True])
def test_authorize_refuses_missing_or_weak_pkce(client, extra, builtin):
    client_id = OAUTH_CLIENT_ID if builtin else _client_id(client)
    params = {'response_type': 'code', 'client_id': client_id, 'redirect_uri': CALLBACK,
              'state': 's', **extra}
    for resp in (client.get('/mcp/oauth/authorize', query_string=params),
                 client.post('/mcp/oauth/authorize', query_string=params,
                             data={**params, 'email': 'test@example.com', 'password': 'TestPassword123!'})):
        assert resp.status_code == 400
        assert 'PKCE' in resp.get_json()['error_description']


def _store_code(user_id, challenge, redirect_uri=CALLBACK):
    from models import MCPOAuthCode, db
    code = secrets.token_urlsafe(32)
    db.session.add(MCPOAuthCode(code=code, user_id=user_id, redirect_uri=redirect_uri,
                                code_challenge=challenge, expires_at=utcnow() + timedelta(minutes=5)))
    db.session.commit()
    return code


def test_code_without_challenge_cannot_be_redeemed(client, test_user, cleanup_tokens):
    code = _store_code(test_user.id, '')
    resp = client.post('/mcp/oauth/token', data={'grant_type': 'authorization_code', 'code': code,
                                                 'code_verifier': 'anything-at-all'})
    assert resp.status_code == 400
    assert resp.get_json()['error'] == 'invalid_grant'


def test_code_without_challenge_refused_even_for_builtin_secret(client, test_user, cleanup_tokens):
    from routes.mcp import OAUTH_CLIENT_SECRET
    code = _store_code(test_user.id, '')
    resp = client.post('/mcp/oauth/token', data={'grant_type': 'authorization_code', 'code': code,
                                                 'client_id': OAUTH_CLIENT_ID,
                                                 'client_secret': OAUTH_CLIENT_SECRET})
    assert resp.status_code == 400
    assert resp.get_json()['error'] == 'invalid_grant'


def test_redirect_uri_mismatch_at_token_refused(client, test_user, cleanup_tokens):
    verifier, challenge = _pkce_pair()
    code = _store_code(test_user.id, challenge)
    resp = client.post('/mcp/oauth/token', data={'grant_type': 'authorization_code', 'code': code,
                                                 'code_verifier': verifier,
                                                 'redirect_uri': 'https://evil.example/cb'})
    assert resp.status_code == 400
    assert resp.get_json()['error'] == 'invalid_grant'


def test_valid_pkce_code_still_redeems(client, test_user, cleanup_tokens):
    verifier, challenge = _pkce_pair()
    code = _store_code(test_user.id, challenge)
    resp = client.post('/mcp/oauth/token', data={'grant_type': 'authorization_code', 'code': code,
                                                 'code_verifier': verifier, 'redirect_uri': CALLBACK})
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()['access_token']
