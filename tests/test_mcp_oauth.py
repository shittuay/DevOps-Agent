"""
MCP OAuth + transport regression tests (routes/mcp.py).

Covers two production bugs behind the long-standing "still unauthorized"
connector failure:

1. Timezone bug: `_consume_code_db` called `.timestamp()` on a naive UTC
   datetime, which Python interprets as *local* server time — silently
   shifting the expiry check by the server's UTC offset and causing every
   code exchange to fail with `invalid_grant` on non-UTC hosts.

2. Path/resource mismatch: claude.ai custom connectors configured with the
   bare origin (no /mcp path) POSTed JSON-RPC to the GET-only landing page
   (405) and read a root protected-resource document that advertised a
   mismatched resource (…/mcp), so tokens issued by a successful browser
   sign-in were never usable. The fix: the streamable transport answers at
   POST /, and each metadata document advertises the resource path it was
   fetched for.
"""

import base64
import hashlib
import secrets
import time
from unittest.mock import patch

import pytest


INIT_RPC = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-03-26", "capabilities": {}},
}


def _pkce_pair():
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b'=').decode()
    return verifier, challenge


# ── Timezone safety of the auth-code store ───────────────────────────────────

@pytest.fixture
def _restore_localtime():
    """Ensure TZ-dependent C functions (time.mktime, etc.) don't leak across tests."""
    yield
    time.tzset()


@pytest.mark.skipif(not hasattr(time, 'tzset'),
                    reason='time.tzset() is POSIX-only (unavailable on Windows)')
def test_consume_code_db_expiry_is_timezone_safe(app, db_session, test_user, monkeypatch, _restore_localtime):
    """Codes issued via _store_code_db must not appear expired due to server TZ."""
    import os
    from routes import mcp as mcp_module

    # Simulate a server running in a timezone well ahead of UTC (e.g. +14:00) —
    # the exact scenario where the naive .timestamp() bug caused instant
    # "expiry" of every authorization code.
    os.environ['TZ'] = 'Pacific/Kiritimati'
    time.tzset()

    code = 'test-code-tz-safety'
    mcp_module._store_code_db(code, test_user.id, 'https://claude.ai/callback', 'challenge123')

    record = mcp_module._consume_code_db(code)

    assert record is not None
    assert record['user_id'] == test_user.id
    # The code was just issued — it must not read as already expired.
    assert record['expires'] > time.time()
    # And it must be single-use: a second consume returns nothing.
    assert mcp_module._consume_code_db(code) is None


def test_consume_code_db_returns_none_for_unknown_code(app, db_session):
    from routes import mcp as mcp_module

    assert mcp_module._consume_code_db('does-not-exist') is None


# ── Login-timing side channel on the OAuth authorize form ────────────────────

class TestOAuthAuthorizeLoginTimingSideChannel:
    """The OAuth authorize POST implemented its own `if not user or not
    user.check_password(password)` check — the same short-circuit-on-`or`
    shape the main /login route was fixed for (see TestLoginTimingSideChannel
    in test_auth.py): an unknown email skipped bcrypt entirely, making account
    existence distinguishable by response time. Fixed by routing through the
    same `_run_timing_safe_password_check()` helper. Asserting on the
    mechanism (bcrypt always invoked), not wall-clock time, since real timing
    assertions are flaky under CI load.
    """

    def _authorize_params(self, client):
        reg = client.post('/mcp/oauth/register', json={
            'client_name': 'pytest-timing-connector',
            'redirect_uris': ['https://claude.ai/api/mcp/auth_callback'],
        })
        client_id = reg.get_json()['client_id']
        verifier, challenge = _pkce_pair()
        return {
            'client_id': client_id,
            'redirect_uri': 'https://claude.ai/api/mcp/auth_callback',
            'state': 'st4te',
            'code_challenge': challenge,
            'code_challenge_method': 'S256',
        }

    def test_nonexistent_email_still_invokes_bcrypt(self, client):
        params = self._authorize_params(client)
        with patch('routes.auth.bcrypt.checkpw', return_value=False) as mock_checkpw:
            resp = client.post('/mcp/oauth/authorize', query_string=params, data={
                **params,
                'email': 'no-such-user@example.com',
                'password': 'whatever-password',
            })
        assert resp.status_code == 200  # re-renders the form with an error, no redirect
        mock_checkpw.assert_called_once()

    def test_wrong_password_invokes_bcrypt_against_real_hash(self, client, test_user):
        params = self._authorize_params(client)
        with patch('routes.auth.bcrypt.checkpw', return_value=False) as mock_checkpw:
            resp = client.post('/mcp/oauth/authorize', query_string=params, data={
                **params,
                'email': 'test@example.com',
                'password': 'WrongPassword123!',
            })
        assert resp.status_code == 200
        mock_checkpw.assert_called_once()
        args = mock_checkpw.call_args.args
        assert args[0] == b'WrongPassword123!'
        assert args[1] == test_user.password_hash.encode('utf-8')


# ── Transport paths ──────────────────────────────────────────────────────────

class TestMCPTransportPaths:
    def test_root_post_serves_mcp_unauthorized(self, client):
        """POST / must reach the MCP transport (401 JSON-RPC), never a 405."""
        resp = client.post('/', json=INIT_RPC)
        assert resp.status_code == 401
        body = resp.get_json()
        assert body['jsonrpc'] == '2.0'
        assert body['error']['code'] == -32000
        challenge = resp.headers.get('WWW-Authenticate', '')
        assert 'resource_metadata=' in challenge
        # Root-path request → root metadata document (no /mcp suffix)
        assert challenge.rstrip('"').endswith('/.well-known/oauth-protected-resource')

    def test_mcp_post_challenge_points_to_mcp_metadata(self, client):
        resp = client.post('/mcp', json=INIT_RPC)
        assert resp.status_code == 401
        challenge = resp.headers.get('WWW-Authenticate', '')
        assert challenge.rstrip('"').endswith('/.well-known/oauth-protected-resource/mcp')

    def test_get_root_still_serves_landing_page(self, client):
        resp = client.get('/')
        assert resp.status_code == 200
        assert b'jsonrpc' not in resp.data


# ── Discovery metadata ───────────────────────────────────────────────────────

class TestOAuthMetadata:
    def test_protected_resource_root_matches_root(self, client):
        doc = client.get('/.well-known/oauth-protected-resource').get_json()
        assert not doc['resource'].endswith('/mcp')
        assert doc['authorization_servers'] == [doc['resource']]

    def test_protected_resource_mcp_matches_mcp(self, client):
        doc = client.get('/.well-known/oauth-protected-resource/mcp').get_json()
        assert doc['resource'].endswith('/mcp')
        assert doc['resource'] == doc['authorization_servers'][0] + '/mcp'

    def test_authorization_server_metadata_and_path_variant(self, client):
        root = client.get('/.well-known/oauth-authorization-server')
        variant = client.get('/.well-known/oauth-authorization-server/mcp')
        assert root.status_code == 200 and variant.status_code == 200
        assert root.get_json() == variant.get_json()
        doc = root.get_json()
        assert doc['authorization_endpoint'].endswith('/mcp/oauth/authorize')
        assert doc['token_endpoint'].endswith('/mcp/oauth/token')
        assert 'S256' in doc['code_challenge_methods_supported']
        assert 'none' in doc['token_endpoint_auth_methods_supported']


# ── Full flow ────────────────────────────────────────────────────────────────

class TestOAuthFlowEndToEnd:
    def test_full_pkce_flow_then_initialize_on_both_paths(self, client, test_user):
        # 1. Dynamic client registration
        reg = client.post('/mcp/oauth/register', json={
            'client_name': 'pytest-connector',
            'redirect_uris': ['https://claude.ai/api/mcp/auth_callback'],
        })
        assert reg.status_code == 201
        client_id = reg.get_json()['client_id']

        # 2. Authorize: login form GET, then credential POST → 302 with code
        verifier, challenge = _pkce_pair()
        params = {
            'response_type': 'code',
            'client_id': client_id,
            'redirect_uri': 'https://claude.ai/api/mcp/auth_callback',
            'state': 'st4te',
            'code_challenge': challenge,
            'code_challenge_method': 'S256',
        }
        form_page = client.get('/mcp/oauth/authorize', query_string=params)
        assert form_page.status_code == 200

        authz = client.post('/mcp/oauth/authorize', query_string=params, data={
            'client_id': client_id,
            'redirect_uri': 'https://claude.ai/api/mcp/auth_callback',
            'state': 'st4te',
            'code_challenge': challenge,
            'code_challenge_method': 'S256',
            'email': 'test@example.com',
            'password': 'TestPassword123!',
        })
        assert authz.status_code == 302
        location = authz.headers['Location']
        assert location.startswith('https://claude.ai/api/mcp/auth_callback')
        assert 'state=st4te' in location
        code = location.split('code=')[1].split('&')[0]

        # 3. Token exchange (public client, PKCE only — no client_secret)
        tok = client.post('/mcp/oauth/token', data={
            'grant_type': 'authorization_code',
            'code': code,
            'code_verifier': verifier,
            'client_id': client_id,
            'redirect_uri': 'https://claude.ai/api/mcp/auth_callback',
        })
        assert tok.status_code == 200, tok.get_json()
        token = tok.get_json()['access_token']

        # 4. The token must work on BOTH the /mcp path and the origin root
        for path in ('/mcp', '/'):
            resp = client.post(path, json=INIT_RPC,
                               headers={'Authorization': f'Bearer {token}'})
            assert resp.status_code == 200, f'{path}: {resp.data[:200]}'
            result = resp.get_json()['result']
            assert result['serverInfo']['name'] == 'DevOps Agent'

        # 5. Auth code is single-use
        replay = client.post('/mcp/oauth/token', data={
            'grant_type': 'authorization_code',
            'code': code,
            'code_verifier': verifier,
            'client_id': client_id,
        })
        assert replay.status_code == 400
        assert replay.get_json()['error'] == 'invalid_grant'

        # Cleanup: token rows FK-reference the user; remove them so the
        # test_user fixture teardown can delete the user cleanly.
        from models import MCPOAuthToken, db
        MCPOAuthToken.query.filter_by(user_id=test_user.id).delete()
        db.session.commit()

    def test_refresh_token_grant_rotates_and_authenticates(self, client, test_user):
        reg = client.post('/mcp/oauth/register', json={
            'client_name': 'refresh-test-client',
            'redirect_uris': ['https://claude.ai/api/mcp/auth_callback'],
        })
        client_id = reg.get_json()['client_id']

        verifier, challenge = _pkce_pair()
        params = {
            'response_type': 'code',
            'client_id': client_id,
            'redirect_uri': 'https://claude.ai/api/mcp/auth_callback',
            'state': 's',
            'code_challenge': challenge,
            'code_challenge_method': 'S256',
        }
        authz = client.post('/mcp/oauth/authorize', query_string=params, data={
            **params, 'email': 'test@example.com', 'password': 'TestPassword123!',
        })
        assert authz.status_code == 302
        # RFC 9207: authorization response carries the issuer
        assert 'iss=' in authz.headers['Location']
        code = authz.headers['Location'].split('code=')[1].split('&')[0]

        tok = client.post('/mcp/oauth/token', data={
            'grant_type': 'authorization_code',
            'code': code,
            'code_verifier': verifier,
            'client_id': client_id,
        })
        assert tok.status_code == 200
        assert tok.headers.get('Cache-Control') == 'no-store'
        body = tok.get_json()
        refresh1 = body['refresh_token']

        # Refresh tokens must NOT authenticate MCP requests directly
        resp = client.post('/mcp', json=INIT_RPC,
                           headers={'Authorization': f'Bearer {refresh1}'})
        assert resp.status_code == 401

        # A refresh token is bound to the client_id it was issued to — a
        # different client_id must not be able to redeem it.
        wrong_client = client.post('/mcp/oauth/token', data={
            'grant_type': 'refresh_token',
            'refresh_token': refresh1,
            'client_id': 'some-other-client',
        })
        assert wrong_client.status_code == 400
        assert wrong_client.get_json()['error'] == 'invalid_grant'

        # Exchange the refresh token for a new pair
        ref = client.post('/mcp/oauth/token', data={
            'grant_type': 'refresh_token',
            'refresh_token': refresh1,
            'client_id': client_id,
        })
        assert ref.status_code == 200, ref.get_json()
        new = ref.get_json()
        assert new['access_token'] != body['access_token']
        assert new['refresh_token'] != refresh1

        # New access token works; old refresh token is single-use (rotated out)
        resp = client.post('/mcp', json=INIT_RPC,
                           headers={'Authorization': f'Bearer {new["access_token"]}'})
        assert resp.status_code == 200
        replay = client.post('/mcp/oauth/token', data={
            'grant_type': 'refresh_token',
            'refresh_token': refresh1,
            'client_id': client_id,
        })
        assert replay.status_code == 400
        assert replay.get_json()['error'] == 'invalid_grant'

        from models import MCPOAuthToken, db
        MCPOAuthToken.query.filter_by(user_id=test_user.id).delete()
        db.session.commit()

    def test_register_echoes_grant_types(self, client):
        reg = client.post('/mcp/oauth/register', json={
            'client_name': 'strict-client',
            'redirect_uris': ['https://claude.ai/api/mcp/auth_callback'],
            'grant_types': ['authorization_code', 'refresh_token'],
            'response_types': ['code'],
        })
        assert reg.status_code == 201
        doc = reg.get_json()
        assert doc['grant_types'] == ['authorization_code', 'refresh_token']
        assert doc['response_types'] == ['code']
        assert doc['client_name'] == 'strict-client'

    def test_non_https_redirect_uri_rejected_but_loopback_allowed(self, client):
        reg = client.post('/mcp/oauth/register', json={
            'client_name': 'loopback-test-client',
            'redirect_uris': ['http://localhost:33418/callback'],
        })
        client_id = reg.get_json()['client_id']
        base = {
            'response_type': 'code',
            'client_id': client_id,
            'code_challenge': 'x' * 43,
            'code_challenge_method': 'S256',
        }
        bad = client.get('/mcp/oauth/authorize',
                         query_string={**base, 'redirect_uri': 'http://evil.example.com/cb'})
        assert bad.status_code == 400
        ok = client.get('/mcp/oauth/authorize',
                        query_string={**base, 'redirect_uri': 'http://localhost:33418/callback'})
        assert ok.status_code == 200

    def test_unregistered_client_id_rejected(self, client):
        """A client_id that never went through /mcp/oauth/register must be rejected —
        otherwise an attacker could reuse a known client_id with their own redirect_uri."""
        resp = client.get('/mcp/oauth/authorize', query_string={
            'response_type': 'code',
            'client_id': 'never-registered-client',
            'redirect_uri': 'https://attacker.example.com/cb',
            'code_challenge': 'x' * 43,
            'code_challenge_method': 'S256',
        })
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'invalid_client'

    def test_repeat_registration_with_same_redirect_uris_reuses_client_id(self, client):
        """claude.ai calls POST /register again on every single reconnect attempt with
        an otherwise-identical payload. If we minted a brand-new client_id each time,
        a client that tracks connection state by client_id would never see a stable
        identity across reconnects, and could plausibly never settle into a
        'connected' state even though each individual token issued is valid."""
        payload = {
            'client_name': 'Claude',
            'redirect_uris': ['https://claude.ai/api/mcp/idempotency-test-callback'],
        }
        first = client.post('/mcp/oauth/register', json=payload)
        second = client.post('/mcp/oauth/register', json=payload)
        third = client.post('/mcp/oauth/register', json=payload)
        assert first.status_code == 201
        assert second.status_code == 201
        assert third.status_code == 201
        client_id = first.get_json()['client_id']
        assert second.get_json()['client_id'] == client_id
        assert third.get_json()['client_id'] == client_id

    def test_registration_with_different_redirect_uris_gets_distinct_client_id(self, client):
        first = client.post('/mcp/oauth/register', json={
            'client_name': 'app-a',
            'redirect_uris': ['https://app-a.example.com/callback'],
        })
        second = client.post('/mcp/oauth/register', json={
            'client_name': 'app-b',
            'redirect_uris': ['https://app-b.example.com/callback'],
        })
        assert first.get_json()['client_id'] != second.get_json()['client_id']

    def test_redirect_uri_must_match_registered_value(self, client):
        reg = client.post('/mcp/oauth/register', json={
            'client_name': 'mismatch-test-client',
            'redirect_uris': ['https://real-app.example.com/cb'],
        })
        client_id = reg.get_json()['client_id']
        resp = client.get('/mcp/oauth/authorize', query_string={
            'response_type': 'code',
            'client_id': client_id,
            'redirect_uri': 'https://attacker.example.com/cb',
            'code_challenge': 'x' * 43,
            'code_challenge_method': 'S256',
        })
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'invalid_request'

    def test_builtin_client_id_rejects_arbitrary_https_redirect_uri(self, client):
        """The well-known default client_id ('claude-connector', printed in this
        module's own docstring) must not accept an arbitrary attacker-controlled
        https redirect_uri — otherwise anyone can start /authorize with that
        client_id and their own redirect_uri, phish a victim through the genuine
        login form, and have the authorization code delivered to their server."""
        from routes.mcp import OAUTH_CLIENT_ID
        resp = client.get('/mcp/oauth/authorize', query_string={
            'response_type': 'code',
            'client_id': OAUTH_CLIENT_ID,
            'redirect_uri': 'https://attacker.example.com/cb',
            'code_challenge': 'x' * 43,
            'code_challenge_method': 'S256',
        })
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'invalid_request'

    def test_builtin_client_id_allows_configured_redirect_uri(self, client):
        from routes.mcp import OAUTH_CLIENT_ID
        resp = client.get('/mcp/oauth/authorize', query_string={
            'response_type': 'code',
            'client_id': OAUTH_CLIENT_ID,
            'redirect_uri': 'https://claude.ai/api/mcp/auth_callback',
            'code_challenge': 'x' * 43,
            'code_challenge_method': 'S256',
        })
        assert resp.status_code == 200

    def test_builtin_client_id_allows_loopback_redirect_uri(self, client):
        from routes.mcp import OAUTH_CLIENT_ID
        resp = client.get('/mcp/oauth/authorize', query_string={
            'response_type': 'code',
            'client_id': OAUTH_CLIENT_ID,
            'redirect_uri': 'http://localhost:54321/callback',
            'code_challenge': 'x' * 43,
            'code_challenge_method': 'S256',
        })
        assert resp.status_code == 200

    def test_registration_without_redirect_uris_rejected(self, client):
        """A DCR client with no redirect_uris on file has nothing for /authorize
        to validate a requested redirect_uri against — reject it at registration
        instead of letting that client_id later accept any redirect_uri."""
        resp = client.post('/mcp/oauth/register', json={'client_name': 'no-redirects-client'})
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'invalid_client_metadata'

        resp2 = client.post('/mcp/oauth/register', json={
            'client_name': 'empty-redirects-client',
            'redirect_uris': [],
        })
        assert resp2.status_code == 400
        assert resp2.get_json()['error'] == 'invalid_client_metadata'

    def test_wrong_pkce_verifier_rejected(self, client, test_user):
        reg = client.post('/mcp/oauth/register', json={
            'client_name': 'any-public-client',
            'redirect_uris': ['https://claude.ai/api/mcp/auth_callback'],
        })
        client_id = reg.get_json()['client_id']

        verifier, challenge = _pkce_pair()
        params = {
            'response_type': 'code',
            'client_id': client_id,
            'redirect_uri': 'https://claude.ai/api/mcp/auth_callback',
            'state': 's',
            'code_challenge': challenge,
            'code_challenge_method': 'S256',
        }
        authz = client.post('/mcp/oauth/authorize', query_string=params, data={
            **params, 'email': 'test@example.com', 'password': 'TestPassword123!',
        })
        assert authz.status_code == 302
        code = authz.headers['Location'].split('code=')[1].split('&')[0]

        tok = client.post('/mcp/oauth/token', data={
            'grant_type': 'authorization_code',
            'code': code,
            'code_verifier': 'wrong-verifier-wrong-verifier-wrong-verifier',
            'client_id': client_id,
        })
        assert tok.status_code == 400
        assert tok.get_json()['error'] == 'invalid_grant'
