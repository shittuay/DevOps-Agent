"""
Database migration script to add security fields to User model
"""
import os
import sys
import codecs

# Fix Windows encoding
if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from app import app, db
from models import User
from sqlalchemy import inspect

def add_security_columns():
    """Add security-related columns to the users table if they don't exist."""
    with app.app_context():
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('users')]

        print("Current columns in users table:", columns)

        # Check which columns need to be added
        columns_to_add = []

        if 'failed_login_attempts' not in columns:
            columns_to_add.append('failed_login_attempts')

        if 'locked_until' not in columns:
            columns_to_add.append('locked_until')

        if 'last_login_ip' not in columns:
            columns_to_add.append('last_login_ip')

        if columns_to_add:
            print(f"\nAdding columns: {', '.join(columns_to_add)}")

            # Add columns using raw SQL
            with db.engine.connect() as conn:
                if 'failed_login_attempts' in columns_to_add:
                    conn.execute(db.text('ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER DEFAULT 0'))
                    print("✓ Added failed_login_attempts column")

                if 'locked_until' in columns_to_add:
                    conn.execute(db.text('ALTER TABLE users ADD COLUMN locked_until DATETIME'))
                    print("✓ Added locked_until column")

                if 'last_login_ip' in columns_to_add:
                    conn.execute(db.text('ALTER TABLE users ADD COLUMN last_login_ip VARCHAR(45)'))
                    print("✓ Added last_login_ip column")

                conn.commit()

            print("\n✅ Security columns added successfully!")
        else:
            print("\n✅ All security columns already exist!")

        # Verify the changes
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('users')]
        print("\nUpdated columns in users table:", columns)

if __name__ == '__main__':
    print("=" * 60)
    print("Database Migration: Adding Security Fields")
    print("=" * 60)

    try:
        add_security_columns()
        print("\n" + "=" * 60)
        print("Migration completed successfully!")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ Error during migration: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
