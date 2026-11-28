"""Signup must not reveal which emails have accounts (2026-11-28 scheduled review).

It used to answer "Email already registered". Now a valid form always shows the same
"Check your email" page; a new account is created unsigned-in and the owner of an existing
address gets an email instead.
"""
from datetime import timedelta
from unittest.mock import patch

import pytest

FORM = {'username': 'freshname', 'password': 'SecurePass123!',
        'confirm_password': 'SecurePass123!', 'full_name': 'Fresh Name', 'terms': 'on'}


def _signup(client, email, **extra):
    return client.post('/signup', data={**FORM, 'email': email, **extra})


def _body(resp):
    import re
    html = resp.get_data(as_text=True)
    # The page names the address typed; take it out before comparing the two responses.
    return re.sub(r'<strong>[^<]*@[^<]*</strong>', '', html)


@pytest.fixture
def no_email_threads():
    with patch('routes.auth.threading.Thread') as thread:
        yield thread


def test_new_and_existing_email_get_the_same_page(client, app, db_session, test_user, no_email_threads):
    from models import User
    new = _signup(client, 'brand-new-signup@example.com')
    existing = _signup(client, test_user.email.upper(), username='othername')
    assert new.status_code == existing.status_code == 200
    assert _body(new) == _body(existing)
    assert 'Check your email' in new.get_data(as_text=True)
    assert 'already registered' not in existing.get_data(as_text=True).lower()
    assert User.query.filter_by(email='brand-new-signup@example.com').count() == 1
    assert User.query.filter(User.email.ilike(test_user.email)).count() == 1


def test_new_signup_is_not_signed_in(client, app, db_session, no_email_threads):
    _signup(client, 'not-signed-in@example.com', username='notsignedin')
    with client.session_transaction() as sess:
        assert '_user_id' not in sess


def test_existing_owner_is_emailed_at_most_hourly(client, app, db_session, test_user, no_email_threads):
    from models import db
    from src.utils.timeutils import utcnow
    _signup(client, test_user.email, username='tryone')
    assert no_email_threads.call_count == 1
    _signup(client, test_user.email, username='trytwo')
    assert no_email_threads.call_count == 1  # throttled
    test_user.signup_notice_sent_at = utcnow() - timedelta(hours=2)
    db.session.commit()
    _signup(client, test_user.email, username='trythree')
    assert no_email_threads.call_count == 2


def test_taken_username_is_still_reported(client, app, db_session, test_user, no_email_threads):
    resp = _signup(client, 'someone-else@example.com', username=test_user.username)
    assert 'Username already taken' in resp.get_data(as_text=True)


def test_plan_picked_before_signup_opens_billing_after_first_sign_in(client, app, db_session, no_email_threads):
    from models import User, db
    _signup(client, 'paid-intent@example.com', username='paidintent', tier_intent='starter')
    user = User.query.filter_by(email='paid-intent@example.com').first()
    user.email_verified = True
    db.session.commit()
    resp = client.post('/login', data={'email': 'paid-intent@example.com', 'password': 'SecurePass123!'})
    assert resp.status_code == 302 and '/billing?upgrade=starter' in resp.headers['Location']


def test_existing_account_notice_text():
    from services.email_service import EmailService

    class U:
        username, email = 'owner', 'owner@example.com'
    svc = EmailService()
    with patch.object(svc, 'send_email', return_value=True) as send:
        svc.send_existing_account_notice(U())
    subject, html = send.call_args[0][1], send.call_args[0][2]
    assert 'already have' in subject
    assert '/forgot-password' in html and 'no new account was created' in html
