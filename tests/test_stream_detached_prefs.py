"""Regression test: /api/chat/stream's generator must not touch request ORM objects.

The generator runs after the view returns, when the request's DB session is gone.
#273 passed `prefs` (a UserPreferences row) into `_swarm_agents_for` inside it, so
reading `prefs.swarm_enabled` raised DetachedInstanceError on every non-sandbox
turn. Claude was never called; chat fell back to Groq and failed (2026-10-17..19).
"""
import ast

REQUEST_ORM_NAMES = {'prefs', 'conv', 'sub', 'conversation', 'subscription', 'current_user'}


def _stream_generators():
    with open('app.py', encoding='utf-8') as f:
        tree = ast.parse(f.read())
    return [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'generate']


def test_stream_generator_exists():
    assert _stream_generators(), "expected the /api/chat/stream generate() closure"


def test_stream_generator_reads_no_request_orm_objects():
    for fn in _stream_generators():
        used = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} & REQUEST_ORM_NAMES
        assert not used, (
            f"generate() at line {fn.lineno} uses {sorted(used)}; read the value in the "
            "view before the generator starts, or re-query by id inside app_context()"
        )


def test_swarm_agents_computed_outside_generator():
    with open('app.py', encoding='utf-8') as f:
        source = f.read()
    assert '_stream_swarm_agents = _swarm_agents_for(model_config, prefs, sandbox_active)' in source
    assert 'swarm_max_agents=_stream_swarm_agents,' in source
