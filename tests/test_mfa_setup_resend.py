"""Setting up email 2FA must offer a way to get a new code.

The setup page's "Verify Code" step had no resend: once the emailed code expired (10 min)
the only way out was to reload and start over, and the error gave no hint of that.
"""
import pathlib
from datetime import timedelta
from unittest.mock import patch

from src.utils.timeutils import utcnow

ROOT = pathlib.Path(__file__).resolve().parents[1]
SETUP_PAGE = (ROOT / 'templates' / 'setup_2fa.html').read_text()
SEND = 'services.email_service.email_service.send_otp_email'


def _capture():
    sent = []
    return sent, (lambda user, code: sent.append(code) or True)


def _start_email_setup(client):
    sent, fake = _capture()
    with patch(SEND, side_effect=fake):
        assert client.post('/api/mfa/set-method', json={'method': 'email'}).status_code == 200
    return sent


def _age_last_send(user, db_session, seconds=61):
    user.mfa_otp_sent_at = utcnow() - timedelta(seconds=seconds)
    db_session.commit()


def test_resend_sends_a_new_code_that_enables_mfa(authenticated_client, test_user, db_session):
    first = _start_email_setup(authenticated_client)
    _age_last_send(test_user, db_session)

    sent, fake = _capture()
    with patch(SEND, side_effect=fake):
        resp = authenticated_client.post('/api/mfa/resend-setup-code')
    assert resp.status_code == 200, resp.get_json()
    assert len(sent) == 1

    stale = authenticated_client.post('/api/mfa/verify-method', json={'code': first[0], 'method': 'email'})
    if first[0] != sent[0]:
        assert stale.status_code == 400

    resp = authenticated_client.post('/api/mfa/verify-method',
                                     json={'code': f'{sent[0][:3]} {sent[0][3:]}', 'method': 'email'})
    assert resp.status_code == 200, resp.get_json()
    db_session.refresh(test_user)
    assert test_user.two_factor_enabled and test_user.mfa_method == 'email'


def test_resend_works_after_the_first_code_expired(authenticated_client, test_user, db_session):
    _start_email_setup(authenticated_client)
    test_user.mfa_otp_expires = utcnow() - timedelta(minutes=1)
    _age_last_send(test_user, db_session, seconds=11 * 60)

    sent, fake = _capture()
    with patch(SEND, side_effect=fake):
        assert authenticated_client.post('/api/mfa/resend-setup-code').status_code == 200
    resp = authenticated_client.post('/api/mfa/verify-method', json={'code': sent[0], 'method': 'email'})
    assert resp.status_code == 200, resp.get_json()


def test_resend_waits_60_seconds(authenticated_client, test_user, db_session):
    _start_email_setup(authenticated_client)
    with patch(SEND, return_value=True) as send:
        resp = authenticated_client.post('/api/mfa/resend-setup-code')
    assert resp.status_code == 429
    send.assert_not_called()


def test_resend_reports_a_failed_send(authenticated_client, test_user, db_session):
    _start_email_setup(authenticated_client)
    _age_last_send(test_user, db_session)
    with patch(SEND, return_value=False):
        assert authenticated_client.post('/api/mfa/resend-setup-code').status_code == 503


def test_resend_refused_when_email_codes_are_already_on(authenticated_client, test_user, db_session):
    test_user.two_factor_enabled = True
    test_user.mfa_method = 'email'
    test_user.mfa_otp_sent_at = None
    db_session.commit()
    with patch(SEND, return_value=True) as send:
        assert authenticated_client.post('/api/mfa/resend-setup-code').status_code == 400
    send.assert_not_called()


def test_resend_needs_a_signed_in_user(client):
    resp = client.post('/api/mfa/resend-setup-code')
    assert resp.status_code in (302, 401)


def test_setup_page_has_a_resend_link_with_a_countdown():
    step = SETUP_PAGE[SETUP_PAGE.index('id="stepOtpVerify"'):SETUP_PAGE.index('id="step1"')]
    assert 'Resend code' in step and 'resendSetupCode()' in step
    assert "fetch('/api/mfa/resend-setup-code'" in SETUP_PAGE
    assert 'startSetupResendTimer();' in SETUP_PAGE


def test_setup_code_box_lets_a_spaced_paste_through():
    box = SETUP_PAGE[SETUP_PAGE.index('id="otpVerifyCode"'):SETUP_PAGE.index('/>', SETUP_PAGE.index('id="otpVerifyCode"'))]
    assert 'maxlength="6"' not in box
    assert ".replace(/[\\s-]/g, '')" in SETUP_PAGE
