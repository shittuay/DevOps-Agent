"""
Route smoke tests.

Walks every GET route registered on the Flask app and asserts none of them
returns a 5xx, both logged out and logged in. This catches the "500 when
visiting page X" class of bug before deploy instead of in production.

Rules with URL parameters are filled with dummy values (int -> 1, string
-> 'smoke'), so routes that look up a specific record are expected to
return 404 for the dummy id — that passes. Only unhandled exceptions
(5xx) fail.

If a route legitimately cannot run in the test environment, add it to
SKIP_ENDPOINTS with a comment saying why — never silently.
"""

import pytest


# Endpoints that cannot be smoke-tested, with the reason. Keep this list
# short: every entry here is a blind spot.
SKIP_ENDPOINTS = {
    'static',  # file serving, not app code
}

# Deliberate non-200 5xx responses, not crashes. api_status_health returns
# 503 by design when a dependency is degraded (always true in tests, where
# external providers are unreachable).
ALLOWED_5XX = {
    'api_status_health': {503},
}


def _dummy_value(converter):
    """Dummy URL parameter value for a werkzeug converter name."""
    if converter in ('int', 'float'):
        return 1
    if converter == 'uuid':
        return '00000000-0000-0000-0000-000000000000'
    # 'string', 'path', 'any', custom converters
    return 'smoke'


def _iter_get_urls(app):
    """Yield (endpoint, url) for every GET rule that can be built."""
    for rule in app.url_map.iter_rules():
        if 'GET' not in rule.methods:
            continue
        if rule.endpoint in SKIP_ENDPOINTS:
            continue
        values = {}
        skip = False
        for arg in rule.arguments:
            converter = rule._converters[arg].__class__.__name__.lower()
            if 'integer' in converter or 'float' in converter:
                values[arg] = 1
            elif 'uuid' in converter:
                values[arg] = _dummy_value('uuid')
            elif 'any' in converter:
                # AnyConverter only accepts its fixed choices; take the first
                try:
                    values[arg] = sorted(rule._converters[arg].items)[0]
                except Exception:
                    skip = True
            else:
                values[arg] = _dummy_value('string')
        if skip:
            continue
        with app.test_request_context():
            from flask import url_for
            try:
                url = url_for(rule.endpoint, **values)
            except Exception:
                continue
        yield rule.endpoint, url


def _smoke(app, client, label):
    """Hit every GET route; collect any 5xx into one failure report."""
    failures = []
    count = 0
    for endpoint, url in _iter_get_urls(app):
        count += 1
        try:
            response = client.get(url, follow_redirects=False)
            status = response.status_code
        except Exception as exc:  # unhandled exception escaping the app
            failures.append(f"{endpoint} ({url}): raised {type(exc).__name__}: {exc}")
            continue
        if status >= 500 and status not in ALLOWED_5XX.get(endpoint, ()):
            failures.append(f"{endpoint} ({url}): {status}")
    assert count > 50, f"URL map looks wrong — only {count} GET routes found"
    assert not failures, (
        f"{len(failures)}/{count} GET routes returned 5xx ({label}):\n  "
        + "\n  ".join(sorted(failures))
    )


def test_get_routes_anonymous(app, client):
    """No GET route may 500 for a logged-out visitor."""
    _smoke(app, client, 'anonymous')


def test_get_routes_authenticated(app, authenticated_client):
    """No GET route may 500 for a logged-in user."""
    _smoke(app, authenticated_client, 'authenticated')
