"""Regression test: scheduler user-with-credentials query must not row-DISTINCT.

The monitoring/infra-sync/digest tasks did `db.session.query(User).join(...)
.distinct()`, i.e. SELECT DISTINCT on the whole users row. Postgres can't apply
DISTINCT to a row containing a `json` column (users.backup_codes), so it raised
`could not identify an equality operator for type json` and every scheduler
tick failed — silently, because the suite runs on SQLite where row-DISTINCT is
allowed. This guards the SQL shape instead of behavior.
"""
from services.scheduler import _users_with_credentials_query


def test_query_does_not_distinct_the_user_row(app):
    from models import db
    with app.app_context():
        sql = str(_users_with_credentials_query(db).statement.compile())
        sql_flat = ' '.join(sql.split()).upper()
        # The OUTER query must not be SELECT DISTINCT <user columns> — that's what
        # broke on Postgres. (A DISTINCT on the user_id subquery is fine and expected.)
        assert not sql_flat.startswith('SELECT DISTINCT'), (
            f"outer SELECT must not DISTINCT the full users row: {sql_flat[:80]}"
        )
        # still scoped to users who actually have a cloud credential
        assert 'USER_CLOUD_CREDENTIAL' in sql_flat


def test_query_returns_users(app, test_user):
    """Smoke: the query builds and executes (0 rows is fine — no creds seeded)."""
    from models import db
    with app.app_context():
        assert _users_with_credentials_query(db).count() >= 0
