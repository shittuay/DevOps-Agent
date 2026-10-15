"""Subscription tier definitions, shared by every place that seeds them.

The feature lists are what the Billing page shows customers, so every line must be
something the app actually does. The 2026-10-14 audit removed lines that weren't true:
resource and team-member limits (never enforced), per-tier sync speeds (everyone syncs
the same way), SOC 2 / HIPAA / PCI compliance and PDF compliance reports (the checks
behind them were not real), "Auto-remediation" and "custom rules" (no such feature),
"Audit log export" (the log it exported was never written to) and "Manual sync only"
(free accounts are synced in the background too).

`sync_tier_features()` runs at import so a release updates the Billing page. It only
touches `features` and `description`; prices, credits and limits are changed on purpose
through `/init-database` (which upserts every field), never by a deploy.
"""
import logging

logger = logging.getLogger(__name__)

_SEED_LOCK_KEY = 0x54_49_45_52  # "TIER"

TIER_DEFINITIONS = [
    dict(name='free', display_name='Free', monthly_credits=20, monthly_price=0.0,
         description='Try the DevOps Agent with limited features',
         features=['20 AI messages per month', '1 cloud account', 'Learning & Sandbox mode'],
         max_cloud_accounts=1, max_resources=25, max_team_members=1, sync_interval_minutes=0,
         compliance_frameworks=[], has_pdf_export=False, has_auto_remediation=False, has_sso=False,
         has_audit_export=False),
    dict(name='starter', display_name='Starter', monthly_credits=200, monthly_price=29.0,
         description='For individual developers and solo operators',
         features=['200 AI messages per month', '1 cloud account', 'AWS security checks', 'Email support'],
         max_cloud_accounts=1, max_resources=50, max_team_members=1, sync_interval_minutes=0,
         compliance_frameworks=['soc2'], has_pdf_export=False, has_auto_remediation=False, has_sso=False,
         has_audit_export=False),
    dict(name='professional', display_name='Professional', monthly_credits=1000, monthly_price=99.0,
         description='For growing teams with multi-cloud needs',
         features=['1,000 AI messages per month', '3 cloud accounts (AWS + Azure + GCP)',
                   'AWS security checks', 'Developer REST API access', 'Priority support'],
         max_cloud_accounts=3, max_resources=500, max_team_members=10, sync_interval_minutes=360,
         compliance_frameworks=['soc2', 'hipaa'], has_pdf_export=True, has_auto_remediation=True, has_sso=False,
         has_audit_export=False),
    dict(name='business', display_name='Business', monthly_credits=3000, monthly_price=299.0,
         description='Full-scale automation for large organizations',
         features=['3,000 AI messages per month', 'Unlimited cloud accounts', 'AWS security checks',
                   'SSO / SAML', 'Developer REST API access', 'Dedicated support + SLA'],
         max_cloud_accounts=99, max_resources=99999, max_team_members=99, sync_interval_minutes=15,
         compliance_frameworks=['soc2', 'hipaa', 'pci_dss', 'gdpr', 'iso27001', 'nist', 'cis'],
         has_pdf_export=True, has_auto_remediation=True, has_sso=True, has_audit_export=True),
]

_COPY_FIELDS = ('features', 'description')


def upsert_all_tiers(db) -> tuple:
    """Create missing tiers and update every field of existing ones. Caller commits.

    Used by /init-database and the local `python app.py` start, which are run on purpose.
    """
    from models import SubscriptionTier
    created = updated = 0
    for defn in TIER_DEFINITIONS:
        tier = SubscriptionTier.query.filter_by(name=defn['name']).first()
        if tier is None:
            db.session.add(SubscriptionTier(**defn, is_active=True))
            created += 1
            continue
        changed = False
        for key, val in defn.items():
            if key != 'name' and getattr(tier, key) != val:
                setattr(tier, key, val)
                changed = True
        updated += changed
    return created, updated


def sync_tier_features() -> int:
    """Bring each existing tier's feature list and description up to date (seed_lock commits).

    Missing tiers are not created here (that is /init-database's job), and numeric
    fields are left alone. Returns the number of tiers changed.
    """
    from models import SubscriptionTier, db
    from services.seed_lock import seed_lock

    changed = 0
    with seed_lock(_SEED_LOCK_KEY):
        for defn in TIER_DEFINITIONS:
            tier = SubscriptionTier.query.filter_by(name=defn['name']).first()
            if tier is None:
                continue
            dirty = False
            for key in _COPY_FIELDS:
                if getattr(tier, key) != defn[key]:
                    setattr(tier, key, defn[key])
                    dirty = True
            changed += dirty
    if changed:
        logger.info("Updated feature lists on %d subscription tier(s)", changed)
    return changed
