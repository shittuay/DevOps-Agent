"""UTC clock helper.

`datetime.utcnow()` is deprecated from Python 3.12 (`sonar python:S6903`), so it
has to go. The obvious replacement is a trap in this codebase, which is why this
module exists rather than a 441-site find-and-replace to
`datetime.now(timezone.utc)`.

**Every `db.DateTime` column in `models.py` is naive** — all 156 of them, none
declaring `timezone=True` — so Postgres stores `TIMESTAMP WITHOUT TIME ZONE` and
SQLAlchemy hands back naive datetimes. This app compares a stored timestamp
against "now" in the places where being wrong matters most: password-reset and
MFA token expiry, `guardrail_blocked_until` lockouts, account lockout windows,
cache TTLs, credit periods, and the stale-execution reconciliation in
`routes/workflows.py`.

Swapping in `datetime.now(timezone.utc)` returns an *aware* datetime. Comparing
that with a naive one loaded from the database raises

    TypeError: can't compare offset-naive and offset-aware datetimes

at runtime — converting a deprecation warning into a live crash in the expiry
paths. So this helper deliberately preserves the existing naive-UTC semantics
and is exactly equivalent to what `datetime.utcnow()` returned.

Making the app genuinely timezone-aware is a separate and much larger change: it
needs all 156 columns migrated to `DateTime(timezone=True)` plus a hand-written
`ALTER COLUMN ... TYPE timestamptz` migration, because `app.py`'s startup
auto-migration only runs `ADD COLUMN IF NOT EXISTS` and cannot change the type of
an existing column. This function is the single place that flip would happen.
"""

from datetime import datetime, timezone

__all__ = ['utcnow']


def utcnow() -> datetime:
    """Current UTC time as a **naive** datetime, matching `datetime.utcnow()`.

    The `.replace(tzinfo=None)` is the load-bearing part: it keeps the return
    value comparable with the naive datetimes stored in every `db.DateTime`
    column. Do not "simplify" it away — see this module's docstring.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
