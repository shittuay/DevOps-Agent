"""Seed pre-built workflow templates. Idempotent — safe to run multiple times.

The catalog and seeding logic live in services/starter_workflows.py so app.py can
seed at import under gunicorn; this stays as a manual/one-off CLI entry point.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from services.starter_workflows import seed_workflow_templates, STARTER_WORKFLOWS


def seed():
    with app.app_context():
        db.create_all()
        added = seed_workflow_templates()
        print(f'Seeded {added} workflow templates ({len(STARTER_WORKFLOWS) - added} already existed).')


if __name__ == '__main__':
    seed()
