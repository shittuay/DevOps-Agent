"""Regression test: the pre-built workflow catalog must actually be populated.

Seeding lived only in scripts/seed_workflows.py, which nothing runs on deploy, so
/workflows rendered "No workflows in this category" against an empty table in prod.

Assertions are scoped to the starter catalog by name — the test DB is shared across
modules, so other tests' templates may also be present.
"""
from services.starter_workflows import STARTER_WORKFLOWS, seed_workflow_templates

STARTER_NAMES = {wf['name'] for wf in STARTER_WORKFLOWS}


def test_seed_populates_catalog_and_is_idempotent(app):
    from models import WorkflowTemplate

    with app.app_context():
        seed_workflow_templates()

        # second run must not duplicate
        assert seed_workflow_templates() == 0

        seeded = WorkflowTemplate.query.filter(
            WorkflowTemplate.name.in_(STARTER_NAMES)
        ).all()
        assert len(seeded) == len(STARTER_WORKFLOWS), "seeding duplicated or missed templates"


def test_seed_takes_advisory_lock_on_postgres(app, monkeypatch):
    """The check-then-insert must be serialized — 3 gunicorn workers seed at
    import simultaneously, and unguarded this inserted the catalog once per
    worker (8 templates became 16 in prod on the first deploy)."""
    from models import db

    executed = []
    real_execute = db.session.execute

    def fake_execute(stmt, *args, **kwargs):
        executed.append(str(stmt))
        if 'pg_advisory_xact_lock' in str(stmt):
            return None  # SQLite has no such function
        return real_execute(stmt, *args, **kwargs)

    with app.app_context():
        monkeypatch.setattr(db.engine.dialect, 'name', 'postgresql', raising=False)
        monkeypatch.setattr(db.session, 'execute', fake_execute, raising=False)
        seed_workflow_templates()

    assert any('pg_advisory_xact_lock' in s for s in executed), \
        "seeding must take an advisory lock, or concurrent workers duplicate the catalog"


def test_seed_lock_releases_on_error(app, monkeypatch):
    """A failed seed must roll back, not strand the transaction holding the lock."""
    from models import db
    from services.seed_lock import seed_lock

    rolled_back = []
    monkeypatch.setattr(db.session, 'rollback', lambda: rolled_back.append(True), raising=False)

    with app.app_context():
        try:
            with seed_lock(1234):
                raise RuntimeError('seed blew up')
        except RuntimeError:
            pass

    assert rolled_back, "seed_lock must roll back on error so the lock is released"


def test_seeded_workflows_are_public_and_listable(authenticated_client, app):
    with app.app_context():
        seed_workflow_templates()

    resp = authenticated_client.get('/api/workflows')
    assert resp.status_code == 200, resp.get_data(as_text=True)
    workflows = [w for w in resp.get_json()['workflows'] if w['name'] in STARTER_NAMES]

    # all of them must reach the user — they are public
    assert len(workflows) == len(STARTER_WORKFLOWS)

    # every category chip in templates/workflows.html must match >= 1 workflow,
    # otherwise that filter renders the empty state
    # (read from the template itself, so adding a category means adding its chip)
    import re
    from pathlib import Path
    html = (Path(__file__).resolve().parent.parent / 'templates' / 'workflows.html').read_text()
    chips = set(re.findall(r'class="filter-chip[^"]*" data-category="([^"]+)"', html)) - {'all'}
    assert chips == {w['category'] for w in workflows}

    for w in workflows:
        assert w['steps'], f"{w['name']} has no steps — execute would send an empty prompt"
