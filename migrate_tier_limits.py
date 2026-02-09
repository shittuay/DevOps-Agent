"""
Migration: Add feature limit columns to subscription_tiers table.

Run this once to add the new tier limit columns and update existing tiers.
Safe to run multiple times (checks if columns already exist).
"""
from app import app, db
from models import SubscriptionTier, UserSubscription
from sqlalchemy import inspect, text


TIER_DEFAULTS = {
    'free': {
        'monthly_price': 0.0,
        'monthly_credits': 20,
        'display_name': 'Free',
        'description': 'Try the DevOps Agent with limited features',
        'features': [
            '20 AI messages per month',
            '1 cloud account',
            '25 resources tracked',
            'Manual sync only',
        ],
        'max_cloud_accounts': 1,
        'max_resources': 25,
        'max_team_members': 1,
        'sync_interval_minutes': 0,
        'compliance_frameworks': [],
        'has_pdf_export': False,
        'has_auto_remediation': False,
        'has_sso': False,
        'has_audit_export': False,
    },
    'starter': {
        'monthly_price': 49.0,
        'monthly_credits': 200,
        'display_name': 'Starter',
        'description': 'For individual developers and solo operators',
        'features': [
            '200 AI messages per month',
            '1 cloud account',
            '50 resources tracked',
            'SOC 2 compliance scans',
            'Email support',
        ],
        'max_cloud_accounts': 1,
        'max_resources': 50,
        'max_team_members': 1,
        'sync_interval_minutes': 0,
        'compliance_frameworks': ['soc2'],
        'has_pdf_export': False,
        'has_auto_remediation': False,
        'has_sso': False,
        'has_audit_export': False,
    },
    'professional': {
        'monthly_price': 199.0,
        'monthly_credits': 2000,
        'display_name': 'Pro',
        'description': 'For growing teams with multi-cloud needs',
        'features': [
            '2,000 AI messages per month',
            '3 cloud accounts (AWS + Azure + GCP)',
            '500 resources tracked',
            'Up to 10 team members',
            'SOC 2 + HIPAA compliance',
            'PDF compliance reports',
            'Auto-remediation',
            'Auto-sync every 6 hours',
            'Priority support',
        ],
        'max_cloud_accounts': 3,
        'max_resources': 500,
        'max_team_members': 10,
        'sync_interval_minutes': 360,
        'compliance_frameworks': ['soc2', 'hipaa'],
        'has_pdf_export': True,
        'has_auto_remediation': True,
        'has_sso': False,
        'has_audit_export': False,
    },
    'business': {
        'monthly_price': 799.0,
        'monthly_credits': 99999,
        'display_name': 'Enterprise',
        'description': 'Unlimited automation for large organizations',
        'features': [
            'Unlimited AI messages',
            'Unlimited cloud accounts',
            'Unlimited resources',
            'Unlimited team members',
            'All compliance frameworks',
            'PDF compliance reports',
            'Auto-remediation + custom rules',
            'Auto-sync every 15 minutes',
            'SSO / SAML',
            'Audit log export',
            'Dedicated support + SLA',
        ],
        'max_cloud_accounts': 99,
        'max_resources': 99999,
        'max_team_members': 99,
        'sync_interval_minutes': 15,
        'compliance_frameworks': ['soc2', 'hipaa', 'pci_dss', 'gdpr', 'iso27001', 'nist', 'cis'],
        'has_pdf_export': True,
        'has_auto_remediation': True,
        'has_sso': True,
        'has_audit_export': True,
    },
}

NEW_COLUMNS = [
    ('max_cloud_accounts', 'INTEGER DEFAULT 1'),
    ('max_resources', 'INTEGER DEFAULT 50'),
    ('max_team_members', 'INTEGER DEFAULT 1'),
    ('sync_interval_minutes', 'INTEGER DEFAULT 0'),
    ('compliance_frameworks', 'JSON DEFAULT \'[]\''),
    ('has_pdf_export', 'BOOLEAN DEFAULT 0'),
    ('has_auto_remediation', 'BOOLEAN DEFAULT 0'),
    ('has_sso', 'BOOLEAN DEFAULT 0'),
    ('has_audit_export', 'BOOLEAN DEFAULT 0'),
]

SUBSCRIPTION_COLUMNS = [
    ('payment_failed_at', 'DATETIME'),
]


def migrate():
    print("=" * 60)
    print("Migration: Add tier feature limits")
    print("=" * 60)

    with app.app_context():
        inspector = inspect(db.engine)

        # Add new columns to subscription_tiers
        existing_cols = {col['name'] for col in inspector.get_columns('subscription_tiers')}
        added = 0

        for col_name, col_type in NEW_COLUMNS:
            if col_name not in existing_cols:
                print(f"  Adding column subscription_tiers.{col_name}...")
                db.session.execute(text(
                    f"ALTER TABLE subscription_tiers ADD COLUMN {col_name} {col_type}"
                ))
                added += 1
            else:
                print(f"  Column subscription_tiers.{col_name} already exists, skipping.")

        # Add new columns to user_subscriptions
        existing_sub_cols = {col['name'] for col in inspector.get_columns('user_subscriptions')}

        for col_name, col_type in SUBSCRIPTION_COLUMNS:
            if col_name not in existing_sub_cols:
                print(f"  Adding column user_subscriptions.{col_name}...")
                db.session.execute(text(
                    f"ALTER TABLE user_subscriptions ADD COLUMN {col_name} {col_type}"
                ))
                added += 1
            else:
                print(f"  Column user_subscriptions.{col_name} already exists, skipping.")

        # Create stripe_webhook_events table if missing
        if not inspector.has_table('stripe_webhook_events'):
            print("  Creating stripe_webhook_events table...")
            db.session.execute(text("""
                CREATE TABLE stripe_webhook_events (
                    id VARCHAR(100) PRIMARY KEY,
                    event_type VARCHAR(100) NOT NULL,
                    processed_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            added += 1
        else:
            print("  Table stripe_webhook_events already exists, skipping.")

        db.session.commit()
        print(f"\nSchema changes: {added} additions.\n")

        # Update existing tiers with new values
        print("Updating existing tier definitions...")
        updated = 0

        for tier_name, values in TIER_DEFAULTS.items():
            tier = SubscriptionTier.query.filter_by(name=tier_name).first()
            if tier:
                for key, val in values.items():
                    setattr(tier, key, val)
                updated += 1
                print(f"  Updated '{tier_name}' -> ${values['monthly_price']}/mo, {values['monthly_credits']} credits")
            else:
                print(f"  Tier '{tier_name}' not found, will be created on next init.")

        db.session.commit()
        print(f"\nTiers updated: {updated}")

        # Summary
        all_tiers = SubscriptionTier.query.order_by(SubscriptionTier.monthly_price).all()
        print("\n" + "-" * 60)
        print("Current tier lineup:")
        for t in all_tiers:
            subs = UserSubscription.query.filter_by(tier_id=t.id).count()
            print(f"  {t.display_name:12s} ${t.monthly_price:>7.0f}/mo  {t.monthly_credits:>6,} credits  {subs} subscribers")
        print("-" * 60)

    print("\nMigration complete!")


if __name__ == '__main__':
    migrate()
