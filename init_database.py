"""
Initialize the database with all tables
"""
import os
import sys

# Set database path
os.environ['DATABASE_URL'] = 'sqlite:///devops_agent.db'

from app import app, db
from models import (
    User, Conversation, ChatMessage, UserPreferences, CommandTemplate,
    ResponseFeedback, SubscriptionTier, UserSubscription, CreditPurchase,
    UsageLog, InfrastructureResource, CostOptimization, SecurityFinding,
    Alert, UserCloudCredential, APIKey, AuditLog, InfrastructureChange
)

def init_db():
    """Initialize database and create all tables"""
    with app.app_context():
        print("Creating all database tables...")
        db.create_all()
        print("Database tables created successfully!")

        # Verify tables were created
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        print(f"\nCreated tables: {', '.join(tables)}")

        # Check users table columns
        if 'users' in tables:
            columns = [col['name'] for col in inspector.get_columns('users')]
            print(f"\nUsers table columns ({len(columns)}): {', '.join(columns)}")

            # Verify 2FA columns exist
            required_2fa_columns = [
                'two_factor_enabled', 'two_factor_secret', 'backup_codes',
                'two_factor_verified_at', 'two_factor_attempts', 'two_factor_locked_until'
            ]
            missing = [col for col in required_2fa_columns if col not in columns]
            if missing:
                print(f"\nWARNING: Missing 2FA columns: {', '.join(missing)}")
            else:
                print("\n✓ All 2FA columns present")

if __name__ == "__main__":
    init_db()
