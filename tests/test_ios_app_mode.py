"""Inside the iPhone app there is no buying (App Store guideline 3.1.3(f): a free companion to a
paid web tool may skip Apple's in-app purchase only if the app has no purchasing and no calls
to action to buy elsewhere). A paid-plan account was enough to get a similar SaaS rejected in
2026, so the app must not show prices, plan names, upgrade prompts or links to Billing.

The app marks its requests with IOS_APP_UA_MARKER in the user agent.
"""
import uuid
from pathlib import Path

from flask import g

from services.app_client import (IOS_APP_UA_MARKER, IN_APP_PLAN_RULE, blocked_in_app,
                                 plan_context)
from services.chat_service import generate_upgrade_pitch

ROOT = Path(__file__).resolve().parent.parent
APP_UA = f'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 {IOS_APP_UA_MARKER}/1.0'
PASSWORD = 'Password123!x'
PURCHASE_WORDS = ('$', 'Starter', 'Upgrade', 'upgrade', '/billing')


def test_pitch_in_app_only_says_when_credits_refill():
    web = generate_upgrade_pitch()
    app = generate_upgrade_pitch(in_app=True)
    assert '/billing' in web and 'Starter' in web
    assert 'refill' in app
    assert not any(w in app for w in PURCHASE_WORDS), app


def test_agent_is_told_not_to_sell_in_the_app():
    assert 'Starter plan ($29/month)' in plan_context('free', 3, in_app=False)
    in_app = plan_context('free', 3, in_app=True)
    assert IN_APP_PLAN_RULE in in_app and '$' not in in_app
    assert plan_context('professional', 0, in_app=False) is None
    assert plan_context('professional', 0, in_app=True) == IN_APP_PLAN_RULE
    assert 'browser' not in IN_APP_PLAN_RULE, 'no pointing users elsewhere to buy'


def test_purchase_paths_are_blocked_but_balance_is_not():
    for path in ('/billing', '/billing/success', '/api/credits/create-checkout',
                 '/api/subscription/create-checkout', '/api/billing/prices', '/api/credits/packs'):
        assert blocked_in_app(path), path
    for path in ('/api/subscription', '/api/usage/stats', '/settings', '/chat', '/api/stripe/webhook'):
        assert not blocked_in_app(path), path


def _signed_in_client(app, db):
    from models import User
    tag = uuid.uuid4().hex[:8]
    user = User(email=f'ios-{tag}@example.com', username=f'ios_{tag}', email_verified=True,
                onboarding_completed=True)
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    c = app.test_client()
    g.pop('_login_user', None)
    assert c.post('/login', data={'email': user.email, 'password': PASSWORD}).status_code == 302
    g.pop('_login_user', None)
    return c, user


def test_billing_page_redirects_in_app_and_works_in_a_browser(app, db_session):
    from models import db
    c, user = _signed_in_client(app, db)
    try:
        r = c.get('/billing', headers={'User-Agent': APP_UA})
        assert r.status_code == 302 and r.headers['Location'].endswith('/settings')
        r = c.post('/api/credits/create-checkout', json={}, headers={'User-Agent': APP_UA})
        assert r.status_code == 404
        r = c.get('/billing')
        assert not (r.status_code == 302 and r.headers['Location'].endswith('/settings'))
    finally:
        g.pop('_login_user', None)
        db.session.delete(user)
        db.session.commit()


def test_settings_page_has_no_billing_link_in_app(app, db_session):
    from models import db
    c, user = _signed_in_client(app, db)
    try:
        app_html = c.get('/settings', headers={'User-Agent': APP_UA}).get_data(as_text=True)
        web_html = c.get('/settings').get_data(as_text=True)
        assert 'href="/billing"' in web_html
        assert 'href="/billing"' not in app_html
    finally:
        g.pop('_login_user', None)
        db.session.delete(user)
        db.session.commit()


def test_landing_page_with_prices_is_skipped_in_app(client):
    r = client.get('/', headers={'User-Agent': APP_UA})
    assert r.status_code == 302 and '/login' in r.headers['Location']


def test_templates_gate_every_billing_link():
    chat = (ROOT / 'templates' / 'index.html').read_text()
    assert 'const IOS_APP =' in chat
    assert chat.count("if (!IOS_APP) ctaDiv.innerHTML") == 2
    for name in ('base.html', 'settings.html'):
        html = (ROOT / 'templates' / name).read_text()
        for line in html.splitlines():
            if 'href="/billing"' in line:
                assert 'ios_app' in line, f'{name}: {line.strip()}'
