"""`src/utils/timeutils.utcnow()` must stay a drop-in for `datetime.utcnow()`.

The whole point of the helper is that it changes nothing observable. If it ever
starts returning an aware datetime, every comparison against a value loaded from
a naive `db.DateTime` column raises TypeError at runtime — in token expiry,
account lockout and credit-period checks. These tests are cheap insurance
against a well-meaning "simplification" of the `.replace(tzinfo=None)`.
"""

import ast
import os
import warnings
from datetime import datetime, timedelta, timezone

from src.utils.timeutils import utcnow


def test_returns_naive_datetime():
    """Aware would break comparison with every stored timestamp."""
    assert utcnow().tzinfo is None


def test_matches_utcnow_semantics():
    """Equivalent to the deprecated call it replaces, not to local time."""
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', DeprecationWarning)
        reference = datetime.utcnow()
    assert abs(utcnow() - reference) < timedelta(seconds=5)


def test_is_utc_not_local_time():
    """The bug this would mask: returning naive *local* time instead of UTC.

    Pinned against an independently-derived UTC value rather than against
    utcnow() itself, so a helper that silently dropped to local time fails here
    even in a non-UTC timezone.
    """
    independent_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    assert abs(utcnow() - independent_utc) < timedelta(seconds=5)


def _python_sources():
    skip = {'venv', '.venv', 'node_modules', '__pycache__', '.git', 'htmlcov', 'env'}
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for name in filenames:
            if name.endswith('.py'):
                path = os.path.join(dirpath, name)
                yield os.path.relpath(path, root), path


def test_no_deprecated_utcnow_remains():
    """Invariant: nothing reintroduces `datetime.utcnow`.

    Same shape as scripts/check_security_invariants.py's checks, and for the
    same reason — a per-call-site convention with no automated check is how the
    other opt-in guards in this repo kept growing gaps. This file and the
    helper's own module are the only legitimate mentions.
    """
    allowed = {
        os.path.join('tests', 'test_timeutils.py'),
        os.path.join('src', 'utils', 'timeutils.py'),
    }
    offenders = []
    for rel, path in _python_sources():
        if rel in allowed:
            continue
        try:
            tree = ast.parse(open(path, encoding='utf-8').read())
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == 'utcnow':
                offenders.append(f'{rel}:{node.lineno}')

    assert not offenders, (
        'datetime.utcnow() is deprecated and returns a naive datetime that is '
        'easy to mix up with an aware one. Use src.utils.timeutils.utcnow(). '
        'Offenders: ' + ', '.join(offenders)
    )
