"""Public pages and plan features only promise what the app does (2026-10-14 audit).

Each phrase below was on the landing page, the About page, the in-app Docs or the
Billing page's plan list, and none of it was true: no resource or team-member limits
are enforced, every account syncs the same way, the SOC 2 / HIPAA / PCI checks were
not real, there is no auto-remediation or custom-rule feature, outgoing webhooks were
never sent, the audit log that "Audit log export" exported was never written to, and
the 23% figure had no measurement behind it.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

BANNED = [
    'resources tracked', 'team members', 'Auto-sync every', 'Auto-remediation', 'remediation rules',
    'SOC 2', 'SOC2', 'HIPAA', 'PDF compliance', 'compliance frameworks', 'compliance scans',
    'Audit log export', 'Manual sync only', '23% cost reduction', 'HMAC-signed webhooks',
    'API + webhooks', 'Confirmation gates on all', 'predictive insights', 'Monitoring & Alerts',
]


@pytest.mark.parametrize('page', ['landing.html', 'about.html', 'docs.html', 'index.html'])
def test_public_pages_make_no_unbacked_claims(page):
    html = (ROOT / 'templates' / page).read_text()
    found = [p for p in BANNED if p in html]
    assert not found, f'{page} still claims: {found}'


def test_plan_features_make_no_unbacked_claims():
    from services.subscription_tiers import TIER_DEFINITIONS
    for tier in TIER_DEFINITIONS:
        text = ' | '.join(tier['features']) + ' | ' + tier['description']
        found = [p for p in BANNED if p in text]
        assert not found, f"{tier['name']} plan still lists: {found}"


def test_app_has_one_copy_of_the_tier_list():
    src = (ROOT / 'app.py').read_text()
    assert "features=['" not in src, 'tier feature lists belong in services/subscription_tiers.py only'


def test_sync_updates_copy_but_never_prices(app, db_session):
    from models import SubscriptionTier, db
    from services.subscription_tiers import sync_tier_features, TIER_DEFINITIONS

    tier = SubscriptionTier.query.filter_by(name='professional').first()
    if tier is None:
        tier = SubscriptionTier(name='professional', display_name='Professional', monthly_credits=1000,
                                monthly_price=99.0, is_active=True)
        db.session.add(tier)
    tier.features = ['500 resources tracked', 'SOC 2 + HIPAA compliance']
    tier.monthly_price = 123.0
    db.session.commit()

    assert sync_tier_features() >= 1
    db.session.refresh(tier)
    expected = next(t for t in TIER_DEFINITIONS if t['name'] == 'professional')
    assert tier.features == expected['features']
    assert tier.monthly_price == 123.0, 'a deploy must never change what customers pay'
    assert sync_tier_features() == 0, 'second run has nothing to change'
