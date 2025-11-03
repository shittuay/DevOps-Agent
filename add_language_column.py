"""
Add language column to users table
"""
import sys
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

from app import app, db
from models import User

with app.app_context():
    # Check if language column exists
    from sqlalchemy import inspect
    inspector = inspect(db.engine)
    columns = [col['name'] for col in inspector.get_columns('users')]

    if 'language' not in columns:
        print("Adding language column to users table...")
        # Add the language column
        with db.engine.connect() as conn:
            conn.execute(db.text('ALTER TABLE users ADD COLUMN language VARCHAR(10) DEFAULT \'en\''))
            conn.commit()
        print("✓ Language column added successfully!")
    else:
        print("✓ Language column already exists")

    # Set default language for existing users
    users = User.query.filter((User.language == None) | (User.language == '')).all()
    if users:
        print(f"Setting default language for {len(users)} users...")
        for user in users:
            user.language = 'en'
        db.session.commit()
        print("✓ Default language set for all users")
    else:
        print("✓ All users have language set")

print("\nDatabase migration complete!")
