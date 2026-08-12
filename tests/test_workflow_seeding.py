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
    chips = {'Compute', 'Security', 'Monitoring', 'Storage', 'Database', 'Cost', 'Networking'}
    assert chips == {w['category'] for w in workflows}

    for w in workflows:
        assert w['steps'], f"{w['name']} has no steps — execute would send an empty prompt"
