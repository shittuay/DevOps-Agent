"""Serialize catalog seeding across concurrent gunicorn workers."""
import logging
from contextlib import contextmanager

from sqlalchemy import text

logger = logging.getLogger(__name__)


@contextmanager
def seed_lock(lock_key: int):
    """Make a catalog seed's check-then-insert atomic across processes.

    Production runs 3 sync gunicorn workers; each imports app.py and seeds at
    the same moment, so a plain "read existing names, insert the rest" races and
    more than one worker inserts the whole catalog (observed: 8 templates became
    16 on the first deploy of the workflow seed). A Postgres transaction-level
    advisory lock makes the sequence atomic — it is released automatically on
    commit or rollback, so a crashed worker can't strand it.

    Non-Postgres (SQLite dev/tests) is single-process, so the lock is skipped.
    """
    from models import db

    if db.engine.dialect.name == 'postgresql':
        db.session.execute(text('SELECT pg_advisory_xact_lock(:k)'), {'k': lock_key})
    try:
        yield
        db.session.commit()  # releases the advisory lock
    except Exception:
        db.session.rollback()
        raise
