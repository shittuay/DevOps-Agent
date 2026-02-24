"""
Migration: Add preferred_model_provider column to user_preferences table.
Idempotent — safe to re-run.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app, db
from sqlalchemy import inspect, text


def migrate():
    with app.app_context():
        inspector = inspect(db.engine)
        if 'user_preferences' not in inspector.get_table_names():
            print("Table user_preferences does not exist yet — run db.create_all() first.")
            return

        columns = [col['name'] for col in inspector.get_columns('user_preferences')]

        if 'preferred_model_provider' in columns:
            print("Column preferred_model_provider already exists — nothing to do.")
            return

        with db.engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE user_preferences ADD COLUMN preferred_model_provider VARCHAR(20) DEFAULT NULL"
            ))
            conn.commit()

        print("Added preferred_model_provider column to user_preferences.")


if __name__ == '__main__':
    migrate()
