"""
Database migration: add ai_model column to usage_logs table
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app, db
from sqlalchemy import inspect


def migrate():
    with app.app_context():
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('usage_logs')]

        if 'ai_model' not in columns:
            print("Adding ai_model column to usage_logs...")
            with db.engine.connect() as conn:
                conn.execute(db.text('ALTER TABLE usage_logs ADD COLUMN ai_model VARCHAR(100)'))
                conn.commit()
            print("ai_model column added successfully.")
        else:
            print("ai_model column already exists — nothing to do.")


if __name__ == '__main__':
    try:
        migrate()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
