"""A correct 2FA code must be accepted, end to end through /login -> /verify-2fa.

Users reported authenticator codes being "not accepted". Causes found and pinned here:
- the code box had maxlength=6, so a pasted "123 456" became "123 45" (5 digits);
- the code screen expired after 5 minutes and silently bounced to /login, while emailed
  codes stay valid for 10;
- emailed codes with a space were compared as typed;
- email codes could not be chosen until the email was "verified" via Settings, which is
  locked until 2FA exists.
"""
import pathlib
import time
from datetime import timedelta
from unittest.mock import patch

import pyotp
import pytest

from src.utils.timeutils import utcnow

ROOT = pathlib.Path(__file__).resolve().parents[1]
PASSWORD = 'TestPassword123!'


@pytest.fixture
def totp_user(test_user, db_session):
    secret = pyotp.random_base32()
    test_user.two_factor_secret = secret
    test_user.two_factor_enabled = True
    test_user.mfa_method = 'totp'
    test_user.two_factor_attempts = 0
    test_user.two_factor_locked_until = None
    db_session.commit()
    return test_user, pyotp.TOTP(secret)


def _start_login(client):
    resp = client.post('/login', data={'email': 'test@example.com', 'password': PASSWORD})
    assert resp.status_code == 302 and '/verify-2fa' in resp.headers['Location']


def _submit(client, code):
    return client.post('/verify-2fa', data={'code': code})


def _logged_in(resp):
    return resp.status_code == 302 and '/verify-2fa' not in resp.headers['Location'] \
        and '/login' not in resp.headers['Location']


@pytest.mark.parametrize('shape', ['plain', 'space', 'nbsp', 'dash'])
def test_current_authenticator_code_is_accepted_however_it_was_pasted(client, totp_user, shape):
    _, totp = totp_user
    _start_login(client)
    code = totp.now()
    code = {'plain': code, 'space': f'{code[:3]} {code[3:]}',
            'nbsp': f'{code[:3]} {code[3:]}', 'dash': f'{code[:3]}-{code[3:]}'}[shape]
    assert _logged_in(_submit(client, code))


def test_code_from_the_previous_30_seconds_is_accepted(client, totp_user):
    _, totp = totp_user
    _start_login(client)
    assert _logged_in(_submit(client, totp.at(time.time() - 30)))


def test_old_or_wrong_codes_are_rejected(client, totp_user):
    _, totp = totp_user
    _start_login(client)
    resp = _submit(client, totp.at(time.time() - 120))
    assert resp.status_code == 200 and b'Invalid code' in resp.data
    resp = _submit(client, '000000' if totp.now() != '000000' else '111111')
    assert resp.status_code == 200 and b'Invalid code' in resp.data


def test_code_screen_survives_a_slow_email_but_says_when_it_expires(client, totp_user):
    _, totp = totp_user
    _start_login(client)
    with client.session_transaction() as s:
        s['2fa_pending_time'] = (utcnow() - timedelta(minutes=7)).isoformat()
    assert _logged_in(_submit(client, totp.now()))

    client.get('/logout')
    _start_login(client)
    with client.session_transaction() as s:
        s['2fa_pending_time'] = (utcnow() - timedelta(minutes=11)).isoformat()
    resp = _submit(client, totp.now())
    assert resp.status_code == 200 and b'timed out' in resp.data


def test_code_screen_names_the_account(client, totp_user):
    _start_login(client)
    page = client.get('/verify-2fa').get_data(as_text=True)
    assert 'Signing in as' in page and 'test@example.com' in page


def test_emailed_code_with_a_space_is_accepted(client, test_user, db_session):
    test_user.mfa_method = 'email'
    test_user.two_factor_enabled = True
    test_user.two_factor_attempts = 0
    db_session.commit()
    sent = {}
    with patch('services.email_service.email_service.send_otp_email',
               side_effect=lambda user, code: sent.setdefault('code', code) or True):
        _start_login(client)
    code = sent['code']
    assert _logged_in(_submit(client, f'{code[:3]} {code[3:]}'))


def test_email_codes_can_be_chosen_without_a_prior_email_verification(authenticated_client, test_user,
                                                                       db_session):
    test_user.email_verified = False
    db_session.commit()
    with patch('services.email_service.email_service.send_otp_email', return_value=True):
        resp = authenticated_client.post('/api/mfa/set-method', json={'method': 'email'})
    assert resp.status_code == 200, resp.get_json()


def test_code_box_lets_a_spaced_paste_through_and_submits_once():
    page = (ROOT / 'templates' / 'verify_2fa.html').read_text()
    box = page[page.index('id="totpCode"'):page.index('/>', page.index('id="totpCode"'))]
    assert 'maxlength="6"' not in box, 'a pasted "123 456" would be cut to 5 digits'
    assert ".replace(/\\D/g, '').slice(0, 6)" in page
    assert '!submitting' in page


def test_setup_page_names_the_account_and_offers_sign_out():
    page = (ROOT / 'templates' / 'setup_2fa.html').read_text()
    assert 'Signed in as' in page and 'href="/logout"' in page
