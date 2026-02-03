"""
Migration script for Phase 5 Features:
- Organizations & Multi-tenancy
- Webhooks
- Compliance Framework
- AI Infrastructure
- Analytics Dashboards

Run this script to add all new tables to the database.
"""

import os
import sys

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from app import app, db
from sqlalchemy import inspect, text


def get_existing_tables(inspector):
    """Get list of existing tables."""
    return inspector.get_table_names()


def migrate():
    """Run the migration."""
    with app.app_context():
        inspector = inspect(db.engine)
        existing_tables = get_existing_tables(inspector)

        print("=" * 60)
        print("Phase 5 Features Migration")
        print("=" * 60)
        print(f"\nExisting tables: {len(existing_tables)}")

        # New tables to create
        new_tables = [
            'organizations',
            'organization_members',
            'teams',
            'team_members',
            'webhook_endpoints',
            'webhook_deliveries',
            'compliance_frameworks',
            'compliance_policies',
            'compliance_reports',
            'infrastructure_templates',
            'provisioning_requests',
            'analytics_dashboards',
            'analytics_widgets'
        ]

        tables_to_create = [t for t in new_tables if t not in existing_tables]

        if not tables_to_create:
            print("\nAll tables already exist. Nothing to migrate.")
            return

        print(f"\nTables to create: {', '.join(tables_to_create)}")

        # Create all tables
        print("\nCreating tables...")
        db.create_all()

        # Verify creation
        inspector = inspect(db.engine)
        new_existing = get_existing_tables(inspector)

        created = []
        failed = []
        for table in tables_to_create:
            if table in new_existing:
                created.append(table)
                print(f"  [OK] {table}")
            else:
                failed.append(table)
                print(f"  [FAILED] {table}")

        print("\n" + "=" * 60)
        print(f"Migration Summary:")
        print(f"  Created: {len(created)} tables")
        print(f"  Failed: {len(failed)} tables")
        print("=" * 60)

        if failed:
            print("\nFailed tables:")
            for t in failed:
                print(f"  - {t}")
            return False

        print("\nMigration completed successfully!")
        return True


def add_missing_columns():
    """Add any missing columns to existing tables."""
    with app.app_context():
        inspector = inspect(db.engine)

        # Check for missing 2FA columns in users table
        if 'users' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('users')]

            two_fa_columns = [
                ('two_factor_enabled', 'BOOLEAN DEFAULT FALSE'),
                ('two_factor_secret', 'VARCHAR(32)'),
                ('backup_codes', 'TEXT'),
                ('two_factor_verified_at', 'TIMESTAMP'),
                ('two_factor_attempts', 'INTEGER DEFAULT 0'),
                ('two_factor_locked_until', 'TIMESTAMP'),
            ]

            for col_name, col_type in two_fa_columns:
                if col_name not in columns:
                    try:
                        db.session.execute(text(
                            f'ALTER TABLE users ADD COLUMN {col_name} {col_type}'
                        ))
                        print(f"  Added column: users.{col_name}")
                    except Exception as e:
                        print(f"  Column {col_name} may already exist: {e}")

            db.session.commit()


if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("DevOps Agent - Phase 5 Database Migration")
    print("=" * 60)

    try:
        # First add any missing columns
        print("\nChecking for missing columns...")
        add_missing_columns()

        # Then create new tables
        print("\nCreating new tables...")
        success = migrate()

        if success:
            print("\nAll migrations completed successfully!")
            print("\nYou can now restart the application.")
        else:
            print("\nSome migrations failed. Please check the errors above.")
            sys.exit(1)

    except Exception as e:
        print(f"\nError during migration: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
