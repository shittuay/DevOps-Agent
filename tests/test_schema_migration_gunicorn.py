"""Regression: schema migration must run under gunicorn, not just `python app.py`.

`app.py`'s db.create_all() + auto-migration column loop used to live only
inside `if __name__ == '__main__':`, which never executes when gunicorn
imports the module as `app:app`. Every table added to models.py after
initial EC2 provisioning silently never got created in production -- hit
three times (mcp_oauth_clients, an infrastructure_changes column, then
drift_baselines/drift_reports) before being traced to this gap. Fixed by
extracting the logic into `_run_schema_migration()` and calling it from both
the gunicorn-import block (`if __name__ != '__main__' and not _is_testing`)
and the __main__ block.
"""
import ast


def test_schema_migration_called_from_gunicorn_import_path():
    """Static check: the gunicorn-import guard must call _run_schema_migration()
    before it's skipped entirely under `python app.py` (__name__ == '__main__')
    or under pytest (_is_testing). A dynamic import-based test can't exercise
    this branch directly -- it's deliberately gated off during tests, same as
    the agent-init/seeding calls next to it -- so this asserts the source
    structure instead: the call must appear inside the `if __name__ != '__main__'`
    block, not only inside `if __name__ == '__main__'`.
    """
    with open('app.py') as f:
        tree = ast.parse(f.read(), filename='app.py')

    def is_gunicorn_guard(test) -> bool:
        # `__name__ != '__main__'`
        return (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name) and test.left.id == '__name__'
            and len(test.ops) == 1 and isinstance(test.ops[0], ast.NotEq)
        )

    def calls_run_schema_migration(node) -> bool:
        for child in ast.walk(node):
            if (isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                    and child.func.id == '_run_schema_migration'):
                return True
        return False

    found_in_gunicorn_path = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            # Handle `if __name__ != '__main__' and not _is_testing:`
            if isinstance(test, ast.BoolOp) and any(is_gunicorn_guard(v) for v in test.values):
                found_in_gunicorn_path = calls_run_schema_migration(node)
                break
            if is_gunicorn_guard(test):
                found_in_gunicorn_path = calls_run_schema_migration(node)
                break

    assert found_in_gunicorn_path, (
        "_run_schema_migration() must be called from the gunicorn-import "
        "code path (the `if __name__ != '__main__'` block), not only from "
        "`if __name__ == '__main__'` -- otherwise it silently never runs "
        "under the real gunicorn:app WSGI process in production."
    )


def test_run_schema_migration_is_idempotent_against_test_db(app, db_session):
    """The function itself must not raise when called against a DB that
    already has every table/column (the normal steady-state case)."""
    from app import _run_schema_migration

    _run_schema_migration()
    _run_schema_migration()
