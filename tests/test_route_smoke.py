"""
Route smoke tests.

Walks every route registered on the Flask app and asserts none returns an
unhandled 5xx, both logged out and logged in. This catches the "500 when
visiting page X" / "500 when clicking button Y" class of bug before deploy
instead of in production (see PRs #72-#74).

GET routes are hit as-is. POST/PUT/PATCH/DELETE routes are hit with an
empty JSON body: a well-behaved endpoint must reject bad input with a 4xx,
not crash. Rules with URL parameters are filled with dummy values (int ->
1, string -> 'smoke'), so record-lookup routes are expected to 404 - that
passes. Only unhandled exceptions (5xx) fail.

If a route legitimately cannot be smoke-tested in the test environment,
add it to SKIP_ENDPOINTS or ALLOWED_5XX with a comment saying why - never
silently.
"""

MUTATING_METHODS = ('POST', 'PUT', 'PATCH', 'DELETE')

# Endpoints that cannot be smoke-tested, with the reason. Keep this list
# short: every entry here is a blind spot.
SKIP_ENDPOINTS = {
    'static',  # file serving, not app code
}

# Deliberate non-crash 5xx responses, all caused by the test environment
# having no external services — each route handles the failure and picks
# its status code on purpose.
ALLOWED_5XX = {
    'api_status_health': {503},   # degraded-dependency health signal
    'get_tools': {503},           # agent not initialized without real API key
    'test_aws_connection': {502}, # upstream AWS unreachable / no credentials
    'sync_status': {500},         # Celery result backend (Redis) absent
    # Agent (Kimi/Claude) is not initialized without a real API key, so these
    # chat-path routes return a deliberate 503 'Agent not initialized'.
    'api_chat': {503},
    'api_chat_stream': {503},
    'clear_conversation': {503},
    'new_conversation': {503},
    # Docker isn't available in CI, so the sandbox runner degrades to 503.
    'run_sandbox_command': {503},
    # Stripe price IDs aren't configured in the test env, so a real checkout
    # attempt fails; validation (bad pack size, disabled Stripe) still 4xx/503.
    'billing.create_credits_checkout_session': {500},
    # Deliberate fail-closed response: no cloud API call is ever made here
    # (see CLAUDE.md's "every feature runs against a real cloud account" rule),
    # so every call returns 501 regardless of the dummy rec_id, unlike its
    # sibling Apply endpoint (app.py's dashboard apply), which happens to
    # 403/404 first in this test environment before reaching its own 501.
    'ai_infrastructure.api_apply_recommendation': {501},
}


def _dummy_url_values(rule):
    """Dummy URL parameter values for a rule, or None if unbuildable."""
    values = {}
    for arg in rule.arguments:
        converter = rule._converters[arg].__class__.__name__.lower()
        if 'integer' in converter or 'float' in converter:
            values[arg] = 1
        elif 'uuid' in converter:
            values[arg] = '00000000-0000-0000-0000-000000000000'
        elif 'any' in converter:
            # AnyConverter only accepts its fixed choices; take the first
            try:
                values[arg] = sorted(rule._converters[arg].items)[0]
            except Exception:
                return None
        else:
            values[arg] = 'smoke'
    return values


def _iter_urls(app, method):
    """Yield (endpoint, url) for every rule supporting `method`."""
    from flask import url_for

    for rule in sorted(app.url_map.iter_rules(), key=lambda r: (r.endpoint, r.rule)):
        if method not in rule.methods:
            continue
        if rule.endpoint in SKIP_ENDPOINTS:
            continue
        values = _dummy_url_values(rule)
        if values is None:
            continue
        with app.test_request_context():
            try:
                url = url_for(rule.endpoint, **values)
            except Exception:
                continue
        yield rule.endpoint, url


def _relogin(client):
    client.post('/login', data={
        'email': 'test@example.com',
        'password': 'TestPassword123!',
    })


def _smoke(app, client, method, label, min_routes, logged_in=False):
    """Hit every route supporting `method`; collect 5xx into one report."""
    failures = []
    count = 0
    for endpoint, url in _iter_urls(app, method):
        count += 1
        kwargs = {'method': method, 'follow_redirects': False}
        if method in MUTATING_METHODS:
            kwargs['json'] = {}
        try:
            status = client.open(url, **kwargs).status_code
        except Exception as exc:  # unhandled exception escaping the app
            failures.append(f"{method} {endpoint} ({url}): raised {type(exc).__name__}: {exc}")
            continue
        if status >= 500 and status not in ALLOWED_5XX.get(endpoint, ()):
            failures.append(f"{method} {endpoint} ({url}): {status}")
        # Hitting a logout route de-authenticates the client; restore the
        # session so the rest of the walk stays logged in.
        if logged_in and 'logout' in endpoint:
            _relogin(client)
    assert count >= min_routes, (
        f"URL map looks wrong - only {count} {method} routes found"
    )
    assert not failures, (
        f"{len(failures)}/{count} {method} routes returned 5xx ({label}):\n  "
        + "\n  ".join(sorted(failures))
    )


def test_get_routes_anonymous(app, client):
    """No GET route may 500 for a logged-out visitor."""
    _smoke(app, client, 'GET', 'anonymous', min_routes=50)


def test_get_routes_authenticated(app, authenticated_client):
    """No GET route may 500 for a logged-in user."""
    _smoke(app, authenticated_client, 'GET', 'authenticated', min_routes=50,
           logged_in=True)


def test_mutating_routes_anonymous(app, client):
    """POST/PUT/PATCH/DELETE with an empty body must not 500 logged out."""
    for method in MUTATING_METHODS:
        _smoke(app, client, method, 'anonymous', min_routes=0)


def test_mutating_routes_authenticated(app, authenticated_client, test_subscription):
    """POST/PUT/PATCH/DELETE with an empty body must not 500 logged in.

    A well-behaved endpoint rejects an empty/invalid body with a 4xx.
    test_subscription gives the user credits so credit-gated endpoints get
    past the paywall check into their real handler code.
    """
    for method in MUTATING_METHODS:
        _smoke(app, authenticated_client, method, 'authenticated', min_routes=0,
               logged_in=True)
