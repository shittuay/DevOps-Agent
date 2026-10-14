"""The Claude connector sign-in (/mcp/oauth/authorize) must enforce 2FA.

Until 2026-10-13 it accepted email + password alone and issued an auth code, so
anyone with an account's password could connect their own Claude to it even
though /login would have asked them for a code. Pinned here: no code is issued
before a valid 2FA code; the code step shares /login's checks, counter and
lockout; its token is bound to one authorization request; SSO-enforced
accounts can't use the password route either.
"""
import re
import time
from unittest.mock import patch

import pyotp
import pytest

PASSWORD = 'TestPassword123!'
CALLBACK = 'https://claude.ai/api/mcp/auth_callback'


@pytest.fixture
def totp_user(test_user, db_session):
    secret = pyotp.random_base32()
    test_user.two_factor_secret = secret
    test_user.two_factor_enabled = True
    test_user.mfa_method = 'totp'
    test_user.two_factor_attempts = 0
    test_user.two_factor_locked_until = None
    db_session.commit()
    yield test_user, pyotp.TOTP(secret)
    from models import MCPOAuthToken, db
    MCPOAuthToken.query.filter_by(user_id=test_user.id).delete()
    db.session.commit()


def _params(client, challenge='c' * 43):
    reg = client.post('/mcp/oauth/register', json={'client_name': 'Claude', 'redirect_uris': [CALLBACK]})
    return {'client_id': reg.get_json()['client_id'], 'redirect_uri': CALLBACK, 'state': 'st',
            'code_challenge': challenge, 'code_challenge_method': 'S256'}


def _password_step(client, params, password=PASSWORD):
    return client.post('/mcp/oauth/authorize', query_string=params,
                       data={**params, 'email': 'test@example.com', 'password': password})


def _token_from(page) -> str:
    match = re.search(r'name="mfa_token" value="([^"]+)"', page.get_data(as_text=True))
    assert match, 'expected the 2FA code form'
    return match.group(1)


def _code_step(client, params, token, code=None, **extra):
    data = {**params, 'mfa_token': token, **extra}
    if code is not None:
        data['code'] = code
    return client.post('/mcp/oauth/authorize', query_string=params, data=data)


def _issued_code(resp):
    return resp.status_code == 302 and resp.headers['Location'].startswith(CALLBACK) \
        and 'code=' in resp.headers['Location']


def test_password_alone_issues_no_code_for_a_2fa_account(client, totp_user):
    params = _params(client)
    resp = _password_step(client, params)
    assert resp.status_code == 200
    page = resp.get_data(as_text=True)
    assert 'authenticator' in page and 'test@example.com' in page
    _token_from(resp)


def test_correct_authenticator_code_completes_the_connection(client, totp_user):
    user, totp = totp_user
    user.failed_login_attempts = 2
    from models import db
    db.session.commit()

    params = _params(client)
    token = _token_from(_password_step(client, params))
    code = totp.now()
    resp = _code_step(client, params, token, f'{code[:3]} {code[3:]}')
    assert _issued_code(resp), resp.get_data(as_text=True)[:300]
    assert 'state=st' in resp.headers['Location']

    db.session.refresh(user)
    assert user.failed_login_attempts == 0


def test_wrong_codes_count_toward_the_shared_lockout(client, totp_user):
    user, totp = totp_user
    params = _params(client)
    token = _token_from(_password_step(client, params))
    wrong = '000000' if totp.now() != '000000' else '111111'
    for _ in range(5):
        resp = _code_step(client, params, token, wrong)
        assert resp.status_code == 200
    assert b'locked' in resp.data.lower()

    # Even the right code is refused while locked, on this page and on /login's.
    resp = _code_step(client, params, token, totp.now())
    assert resp.status_code == 200 and b'Too many failed attempts' in resp.data
    from models import db
    db.session.refresh(user)
    assert user.two_factor_locked_until is not None


def test_token_is_bound_to_its_authorization_request(client, totp_user):
    _, totp = totp_user
    params = _params(client)
    token = _token_from(_password_step(client, params))
    other = {**params, 'code_challenge': 'd' * 43}
    resp = _code_step(client, other, token, totp.now())
    assert resp.status_code == 200 and b'could not be verified' in resp.data


def test_forged_or_expired_token_is_refused(client, totp_user):
    _, totp = totp_user
    params = _params(client)
    resp = _code_step(client, params, 'not-a-real-token', totp.now())
    assert resp.status_code == 200 and b'could not be verified' in resp.data

    token = _token_from(_password_step(client, params))
    real_time = time.time
    with patch('time.time', lambda: real_time() + 11 * 60):
        resp = _code_step(client, params, token, totp.now())
    assert resp.status_code == 200 and b'timed out' in resp.data


def test_email_code_account_gets_an_emailed_code_and_can_resend(client, test_user, db_session):
    test_user.mfa_method = 'email'
    test_user.two_factor_enabled = True
    test_user.two_factor_attempts = 0
    db_session.commit()
    sent = []
    with patch('services.email_service.email_service.send_otp_email',
               side_effect=lambda user, code: sent.append(code) or True):
        params = _params(client)
        page = _password_step(client, params)
        assert b'emailed you' in page.data and len(sent) == 1
        token = _token_from(page)

        resend = _code_step(client, params, token, resend='1')
        assert b'wait 60 seconds' in resend.data and len(sent) == 1

        resp = _code_step(client, params, token, sent[-1])
    assert _issued_code(resp)

    from models import MCPOAuthToken
    MCPOAuthToken.query.filter_by(user_id=test_user.id).delete()
    db_session.commit()


def test_account_without_2fa_still_connects_with_its_password(client, test_user):
    params = _params(client)
    assert _issued_code(_password_step(client, params))


def test_sso_enforced_account_cannot_connect_with_a_password(client, test_user):
    params = _params(client)
    with patch('services.sso_service.sso_login_required', return_value=object()):
        resp = _password_step(client, params)
    assert resp.status_code == 200 and b'single sign-on' in resp.data
