"""Signup source tracking and sandbox-first onboarding (owner request, 2026-10-15).

TikTok ads reached ~5,000 people but the admin page couldn't say which signups they
brought, or how far anyone got. And the first screen asked new users to connect a
real cloud account before they had seen the agent do anything.
"""
from pathlib import Path

from werkzeug.datastructures import MultiDict

from services import signup_source as ss

ROOT = Path(__file__).resolve().parent.parent


def test_source_from_link_tags_and_referrers():
    assert ss.source_from(MultiDict({'utm_source': 'TikTok'}), None) == 'tiktok'
    assert ss.source_from(MultiDict({'utm_source': 'tiktok', 'utm_campaign': 'Video 1!'}), None) == 'tiktok/video1'
    assert ss.source_from(MultiDict({'ref': 'linkedin'}), None) == 'linkedin'
    assert ss.source_from(MultiDict(), 'https://www.google.com/search?q=x') == 'site:google.com'
    assert ss.source_from(MultiDict(), 'https://devopsagent.io/pricing') is None
    assert ss.source_from(MultiDict(), None) is None


def test_first_visit_wins():
    session = {}
    ss.remember(session, MultiDict({'utm_source': 'tiktok'}), None)
    ss.remember(session, MultiDict({'utm_source': 'google'}), None)
    assert session[ss.SESSION_KEY] == 'tiktok'


def test_signup_saves_the_source(client, app, db_session):
    from models import User, db
    client.get('/?utm_source=tiktok&utm_campaign=launch')
    client.post('/signup', data={'email': 'src-test@example.com', 'username': 'srctest',
                                 'password': 'SecurePass123!', 'confirm_password': 'SecurePass123!',
                                 'full_name': 'Src Test'})
    user = User.query.filter_by(email='src-test@example.com').first()
    try:
        assert user is not None and user.signup_source == 'tiktok/launch'
    finally:
        if user:
            db.session.delete(user)
            db.session.commit()


def test_report_counts_progress_and_sources(app, db_session):
    from models import User, db
    a = User(email='rep-a@example.com', username='rep_a', role='user', signup_source='tiktok',
             email_verified=True)
    b = User(email='rep-b@example.com', username='rep_b', role='user')
    admin = User(email='rep-admin@example.com', username='rep_admin', role='admin', signup_source='tiktok')
    for u in (a, b, admin):
        u.set_password('Password123!x')
        db.session.add(u)
    db.session.commit()
    try:
        report = ss.signup_report(30)
        funnel = dict(report['funnel'])
        assert funnel['Signed up'] >= 2 and funnel['Verified email'] >= 1
        sources = dict(report['by_source'])
        assert sources['tiktok']['signups'] >= 1
        assert 'rep_admin' not in str(report), 'admin accounts are left out'
        prog = ss.user_progress([a.id, b.id])
        assert prog[a.id]['verified'] is True and prog[b.id]['messages'] == 0
    finally:
        for u in (a, b, admin):
            db.session.delete(u)
        db.session.commit()


def test_onboarding_leads_with_sandbox():
    html = (ROOT / 'templates' / 'onboarding.html').read_text()
    welcome = html[html.index('<div class="btn-group">'):]
    welcome = welcome[:welcome.index('</div>')]
    first_button = welcome[welcome.index('<button'):welcome.index('</button>')]
    assert 'btn-primary' in first_button and 'startSandbox()' in first_button
    assert 'goTo(1)' in welcome, 'connecting a cloud account is still offered'


def test_admin_dashboard_shows_the_report():
    html = (ROOT / 'templates' / 'admin' / 'dashboard.html').read_text()
    assert 'report.funnel' in html and 'report.by_source' in html and 'user.signup_source' in html
    assert 'utm_source=tiktok' in html


def test_admin_dashboard_renders(app, db_session):
    import uuid
    from flask import g
    from models import User, db
    tag = uuid.uuid4().hex[:8]
    admin = User(email=f'adm-{tag}@example.com', username=f'adm_{tag}', role='admin')
    admin.set_password('Password123!x')
    db.session.add(admin)
    db.session.commit()
    try:
        c = app.test_client()
        g.pop('_login_user', None)
        assert c.post('/login', data={'email': admin.email, 'password': 'Password123!x'}).status_code == 302
        g.pop('_login_user', None)
        resp = c.get('/admin/')
        assert resp.status_code == 200, resp.get_data(as_text=True)[:500]
        body = resp.get_data(as_text=True)
        assert 'Signups, last 30 days' in body and 'Where they came from' in body
    finally:
        g.pop('_login_user', None)
        db.session.delete(admin)
        db.session.commit()
