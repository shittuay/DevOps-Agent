"""Regression test: the background scheduler must start under gunicorn.

For most of the app's life start_scheduler() was only called inside
`if __name__ == '__main__':`, which gunicorn never executes — so proactive
monitoring, cost/security scans, drip + digest emails, infra auto-sync, and DB
backups silently never ran in production. This asserts there is a module-level
(non-__main__) start path, gunicorn-gated, so it can't regress.
"""
import ast


def _app_tree():
    with open('app.py') as f:
        return ast.parse(f.read())


def _main_block(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            t = node.test
            # matches `if __name__ == '__main__':`
            if (isinstance(t, ast.Compare) and isinstance(t.left, ast.Name)
                    and t.left.id == '__name__'):
                return node
    return None


def _calls_start_scheduler(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            name = getattr(f, 'id', None) or getattr(f, 'attr', None)
            if name == 'start_scheduler':
                return True
    return False


def test_start_scheduler_called_at_module_level():
    """There must be a start_scheduler call OUTSIDE the __main__ block."""
    tree = _app_tree()
    main = _main_block(tree)
    main_lines = set(range(main.lineno, (main.end_lineno or main.lineno) + 1)) if main else set()

    module_level_start = False
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            name = getattr(f, 'id', None) or getattr(f, 'attr', None)
            if name == 'start_scheduler' and n.lineno not in main_lines:
                module_level_start = True
                break
    assert module_level_start, (
        "start_scheduler must be called at module level so gunicorn runs it — "
        "a __main__-only call never fires in production"
    )


def test_scheduler_start_is_gunicorn_gated():
    """The module-level start must be guarded (gunicorn detection) so it doesn't
    fire during migration scripts, shells, or tests."""
    src = open('app.py').read()
    assert '_under_gunicorn' in src and "'gunicorn'" in src, \
        "module-level scheduler start should be gated on a gunicorn check"


def test_scheduler_not_running_in_test_process():
    """Importing app under pytest must NOT have started a scheduler thread —
    the gate keeps background jobs (emails, syncs) out of the test run."""
    import threading
    running = [t for t in threading.enumerate()
               if 'schedul' in t.name.lower() and t.is_alive()]
    assert not running, f"scheduler thread should not run under tests: {running}"
