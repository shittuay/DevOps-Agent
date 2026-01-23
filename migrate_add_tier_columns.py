"""
Add max_duration_days and daily_action_limit columns to subscription_tiers table.
"""
from app import app, db
from sqlalchemy import text

def migrate():
    """Add new columns to existing database."""
    print("=" * 70)
    print("DATABASE MIGRATION: Adding new columns to subscription_tiers")
    print("=" * 70)
    print()

    with app.app_context():
        try:
            # Add max_duration_days column
            print("Adding max_duration_days column...")
            db.session.execute(text(
                "ALTER TABLE subscription_tiers ADD COLUMN max_duration_days INTEGER"
            ))
            print("[OK] max_duration_days column added")
        except Exception as e:
            if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                print("[SKIP] max_duration_days column already exists")
            else:
                print(f"[ERROR] Failed to add max_duration_days: {e}")

        try:
            # Add daily_action_limit column
            print("Adding daily_action_limit column...")
            db.session.execute(text(
                "ALTER TABLE subscription_tiers ADD COLUMN daily_action_limit INTEGER"
            ))
            print("[OK] daily_action_limit column added")
        except Exception as e:
            if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                print("[SKIP] daily_action_limit column already exists")
            else:
                print(f"[ERROR] Failed to add daily_action_limit: {e}")

        # Commit changes
        db.session.commit()
        print()
        print("=" * 70)
        print("MIGRATION COMPLETE!")
        print("=" * 70)
        print()

if __name__ == '__main__':
    migrate()
