"""CSRF enforcement on cookie-authenticated form submissions.

app.py disables Flask-WTF's automatic check (WTF_CSRF_CHECK_DEFAULT=False)
because the JSON surfaces send no token, and enforces the check itself in
_enforce_csrf_on_form_submissions() for form-encoded/multipart posts only.

That split is the whole point of these tests. Before the hook existed, the only
form endpoints validated at all were the four that call routes/auth.py's
`_check_csrf()` by hand; every other form POST (profile, organization invites
and settings, compliance, API key creation) rendered no token and checked none.
A regression here is silent — the forms keep working, they just stop being
checked — so assert both halves.

The discriminator is the 303 status: app.py's CSRFError handler redirects with
303, which no ordinary /login outcome returns (a bad password re-renders 200, a
good one redirects 302).
"""

import re
import pytest


CSRF_REJECTED = 303


@pytest.fixture
def csrf_app(app):
    """Re-enable CSRF for one test; conftest disables it app-wide.

    conftest's `app` fixture pushes a single app context for the whole session,
    so Flask-WTF's per-request `g.csrf_token` cache outlives the request that
    set it. generate_csrf() short-circuits on that cache, handing this test a
    token whose session half belongs to an earlier test's client -- the POST
    then fails with "The CSRF session token is missing". conftest documents the
    same hazard for `g._login_user`. Production is unaffected: there `g` is torn
    down with the request.
    """
    from flask import g

    original = app.config['WTF_CSRF_ENABLED']
    app.config['WTF_CSRF_ENABLED'] = True
    g.pop('csrf_token', None)
    yield app
    g.pop('csrf_token', None)
    app.config['WTF_CSRF_ENABLED'] = original


def _token_from(html):
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert m, 'login page rendered no csrf_token input'
    return m.group(1)


def test_form_post_without_token_is_rejected(csrf_app, client):
    resp = client.post('/login', data={'email': 'a@b.com', 'password': 'x'})
    assert resp.status_code == CSRF_REJECTED


def test_form_post_with_valid_token_is_not_rejected(csrf_app, client):
    page = client.get('/login')
    token = _token_from(page.get_data(as_text=True))

    resp = client.post('/login', data={
        'email': 'a@b.com', 'password': 'x', 'csrf_token': token,
    })
    assert resp.status_code != CSRF_REJECTED


def test_json_post_is_not_blocked(csrf_app, client):
    """JSON bodies need a CORS preflight no cross-origin page can satisfy, so
    they are deliberately outside the hook — blocking them would break the
    chat UI and every /api/* caller."""
    resp = client.post('/login', json={'email': 'a@b.com', 'password': 'x'})
    assert resp.status_code != CSRF_REJECTED


def test_multipart_post_is_covered(csrf_app, client):
    """multipart/form-data is a simple request too, so it must be enforced."""
    resp = client.post(
        '/login',
        data={'email': 'a@b.com', 'password': 'x'},
        content_type='multipart/form-data',
    )
    assert resp.status_code == CSRF_REJECTED


def test_get_is_never_blocked(csrf_app, client):
    assert client.get('/login').status_code == 200


def test_exempt_blueprint_is_honoured(csrf_app, app):
    """csrf.exempt(...) must keep working: the hook mirrors Flask-WTF's own
    exemption lookup rather than re-deriving it."""
    from app import csrf
    assert csrf._exempt_blueprints, 'no blueprints are exempt; the hook check is untested'
    exempt_names = {bp.name for bp in csrf._exempt_blueprints}
    assert 'api' in exempt_names or 'mcp' in exempt_names


def test_rejection_does_not_open_redirect(csrf_app, client):
    """A forged post carries the attacker's page as Referer. Redirecting back to
    it would hand them an open redirect, so the handler falls back to index."""
    resp = client.post(
        '/login',
        data={'email': 'a@b.com', 'password': 'x'},
        headers={'Referer': 'https://evil.example.com/attack'},
    )
    assert resp.status_code == CSRF_REJECTED
    assert 'evil.example.com' not in resp.headers['Location']


def test_rejection_returns_to_same_origin_referrer(csrf_app, client):
    resp = client.post(
        '/login',
        data={'email': 'a@b.com', 'password': 'x'},
        headers={'Referer': 'http://localhost/login'},
    )
    assert resp.status_code == CSRF_REJECTED
    assert resp.headers['Location'].endswith('/login')
