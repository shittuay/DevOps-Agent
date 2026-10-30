"""Onboarding emails and the weekly summary only say what the app does.

Before 2026-10-30 they promised removed features (proactive alerts), named a host-only
tool (Terraform) as something to try, quoted an invented "early user" saving
"2 hours/day", a fixed "$50-200/mo" in waste, a stale "726 operations", and the weekly
digest graded every account "A (Excellent)" when no security check had ever run.
"""
import re
from types import SimpleNamespace

import pytest

BANNED = [
    r'2 hours', r'early users?', r'real workflow', r'\$50', r'726', r'proactive alert',
    r'terraform', r'monitoring', r'compliance', r'incident', r'health digest',
    r'infrastructure health', r'excellent', r'zero setup', r'cancel',
]


def _user():
    return SimpleNamespace(id=7, username='sam', email='sam@example.com')


def _drip_html(key):
    import services.drip_email_service as d
    return d._build_drip_html(key, _user(), 'https://devopsagent.io')


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'test-secret')


def test_drip_keys_never_change():
    """Keys are what DripEmailLog stores; renaming one re-sends it to everybody."""
    from services.drip_email_service import DRIP_SEQUENCE
    assert [s['key'] for s in DRIP_SEQUENCE] == ['day_2_credits', 'day_5_persona', 'day_14_power', 'day_25_upgrade']


@pytest.mark.parametrize('key', ['day_2_credits', 'day_5_persona', 'day_14_power', 'day_25_upgrade'])
def test_drip_emails_make_no_claims_the_app_cannot_back(key):
    from services.drip_email_service import DRIP_SEQUENCE
    subject = next(s['subject'] for s in DRIP_SEQUENCE if s['key'] == key)
    text = (subject + ' ' + _drip_html(key)).lower()
    for pattern in BANNED:
        assert not re.search(pattern, text), f'{key} still says {pattern!r}'
    assert '/email/unsubscribe?user_id=7' in text


def test_plan_table_comes_from_the_real_plans():
    from services.subscription_tiers import TIER_DEFINITIONS
    html = _drip_html('day_25_upgrade')
    for t in TIER_DEFINITIONS:
        assert t['display_name'] in html
        assert f"{t['monthly_credits']:,}" in html
    assert '$29/mo' in html and '$0' in html
    assert '(Trial)' not in html


def test_welcome_and_low_credit_emails_are_current(monkeypatch):
    import services.email_service as es
    sent = []
    monkeypatch.setattr(es.EmailService, 'send_email', lambda self, to, subj, html, text=None: sent.append(html) or True)
    svc = es.EmailService()
    svc.send_welcome_email(_user())
    svc.send_credit_low_warning(_user(), 3)
    welcome, low = sent
    assert 'refill every month' in welcome and 'Sandbox' in welcome and 'EKS' in welcome
    assert 'Deploy and monitor' not in welcome and 'recommendations' not in welcome
    assert '$10 for 100' not in low


def test_summary_says_when_no_security_check_ran():
    from services.scheduler import _build_digest_html
    html = _build_digest_html('sam', serious_findings=None, rec_count=0, rec_savings=0, waiting_approvals=0)
    assert 'Not run this week' in html
    assert 'No critical or high findings' not in html
    assert 'Excellent' not in html and 'Health' not in html


def test_summary_reports_real_numbers():
    from services.scheduler import _build_digest_html
    html = _build_digest_html('sam', serious_findings=2, rec_count=3, rec_savings=120.4, waiting_approvals=1)
    assert '2 critical or high findings open' in html
    assert '3 new recommendations, about $120/mo (estimate)' in html
    assert '1 waiting for your confirmation' in html


def test_weekly_summary_uses_the_last_check_time(app, db_session, test_user, monkeypatch):
    import services.scheduler as sch
    import services.email_service as es
    from datetime import datetime, timedelta
    from models import UserCloudCredential, db
    db.session.add(UserCloudCredential(user_id=test_user.id, cloud_provider='aws',
                                       credentials_encrypted='x', is_active=True))
    db.session.commit()
    sunday = datetime(2026, 11, 1, 9, 0)
    monkeypatch.setattr(sch, 'utcnow', lambda: sunday)
    bodies, subjects = [], []
    monkeypatch.setattr(es.EmailService, 'send_email',
                        lambda self, to, subj, html, text=None: subjects.append(subj) or bodies.append(html) or True)

    sch._run_weekly_digest(db)
    assert subjects == ['Your DevOps Agent weekly summary']
    assert 'Not run this week' in bodies[0], 'no check ran, so no clean result may be shown'

    test_user.security_checked_at = sunday + timedelta(days=6)
    test_user.last_digest_sent_at = None
    db.session.commit()
    monkeypatch.setattr(sch, 'utcnow', lambda: sunday + timedelta(days=7))
    sch._run_weekly_digest(db)
    assert 'No critical or high findings open' in bodies[1]


def test_a_successful_security_check_is_recorded():
    import inspect
    import services.security_scanner as sc
    src = inspect.getsource(sc.scan_aws_security)
    raise_at = src.index('raise SecurityScanError')
    assert 'security_checked_at = now' in src[raise_at:], 'only a check that read the account counts'


def test_summary_does_not_ask_non_aws_users_to_run_aws_checks():
    from services.scheduler import _build_digest_html
    html = _build_digest_html('sam', None, 0, 0, 0, security_available=False)
    assert 'Available for AWS accounts only' in html and 'Run the security checks' not in html
