"""The iPhone app asks permission before sending anything to the AI providers (App Review
Guideline 5.1.2(i)). Server side: services/ai_consent.py and routes/ai_consent.py; the screen
is static/js/ai_consent.js, run here in node with a small fake DOM."""
import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from flask import g

from services.ai_consent import AI_ENDPOINTS, AI_PROVIDERS, is_ai_endpoint
from services.app_client import IOS_APP_UA_MARKER

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = (ROOT / 'static' / 'js' / 'ai_consent.js').read_text()
APP_UA = f'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 {IOS_APP_UA_MARKER}/1.0'
PASSWORD = 'Password123!x'


def _signed_in(app, db):
    from models import User
    tag = uuid.uuid4().hex[:8]
    user = User(email=f'aic-{tag}@example.com', username=f'aic_{tag}', email_verified=True,
                onboarding_completed=True)
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    c = app.test_client()
    g.pop('_login_user', None)
    assert c.post('/login', data={'email': user.email, 'password': PASSWORD}).status_code == 302
    g.pop('_login_user', None)
    return c, user


def _cleanup(db, user):
    g.pop('_login_user', None)
    db.session.delete(user)
    db.session.commit()


def _consent_blocked(resp):
    return resp.status_code == 403 and (resp.get_json(silent=True) or {}).get('code') == 'ai_consent_required'


def test_every_ai_endpoint_is_listed():
    assert is_ai_endpoint('/api/chat') and is_ai_endpoint('/api/chat/stream/')
    assert not is_ai_endpoint('/api/chat/history') and not is_ai_endpoint('/api/ai-consent')
    # Every route that calls a model must be gated. If you add one, add it to AI_ENDPOINTS.
    assert set(AI_ENDPOINTS) == {'/api/chat', '/api/chat/stream',
                                 '/curriculum/api/ai-guide', '/curriculum/api/quiz/generate',
                                 '/api/learning/session-summary'}


def test_app_requests_are_refused_until_the_user_allows_it(app, db_session):
    from models import db
    c, user = _signed_in(app, db)
    try:
        for path in AI_ENDPOINTS:
            assert _consent_blocked(c.post(path, json={'message': 'hi'}, headers={'User-Agent': APP_UA})), path
            assert not _consent_blocked(c.post(path, json={'message': 'hi'})), f'web gated: {path}'

        assert c.get('/api/ai-consent').get_json() == {'allowed': False, 'allowed_at': None}
        state = c.post('/api/ai-consent', json={}).get_json()
        assert state['allowed'] and state['allowed_at']
        db.session.refresh(user)
        assert user.ai_consent_at is not None
        for path in AI_ENDPOINTS:
            assert not _consent_blocked(c.post(path, json={'message': 'hi'}, headers={'User-Agent': APP_UA})), path

        assert c.delete('/api/ai-consent').get_json()['allowed'] is False
        assert _consent_blocked(c.post('/api/chat', json={'message': 'hi'}, headers={'User-Agent': APP_UA}))
    finally:
        _cleanup(db, user)


def test_consent_endpoints_need_sign_in(client):
    assert client.post('/api/ai-consent', json={}).status_code in (302, 401)


def test_screen_and_settings_box_only_in_the_app(app, db_session):
    from models import db
    c, user = _signed_in(app, db)
    try:
        app_settings = c.get('/settings', headers={'User-Agent': APP_UA}).get_data(as_text=True)
        web_settings = c.get('/settings').get_data(as_text=True)
        assert 'id="aiConsentBox"' in app_settings and 'js/ai_consent.js' in app_settings
        assert 'id="aiConsentBox"' not in web_settings and 'js/ai_consent.js' not in web_settings
        assert 'data-ai-consent="0"' in app_settings
    finally:
        _cleanup(db, user)


def test_every_page_that_calls_ai_loads_the_screen():
    for name in ('base.html', 'index.html', 'curriculum/phase.html'):
        html = (ROOT / 'templates' / name).read_text()
        assert "js/ai_consent.js" in html and 'data-ai-consent=' in html, name
        line = next(l for l in html.splitlines() if 'js/ai_consent.js' in l)
        assert 'ios_app' in line, name


def test_screen_names_the_same_providers_as_the_server_and_the_policy():
    js_names = re.findall(r"\['([^']+)', '", SCRIPT)
    assert js_names == [name for name, _ in AI_PROVIDERS]
    policy = (ROOT / 'templates' / 'privacy-policy.html').read_text()
    for name, _ in AI_PROVIDERS:
        assert name in policy
    assert 'asks your permission' in policy


HARNESS = r"""
const created = [];
function node(tag) {
  const n = {tag, attrs: {}, children: [], listeners: {}, style: {}, textContent: '', parentNode: null, disabled: false,
    setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k]; },
    appendChild(c) { c.parentNode = this; this.children.push(c); return c; },
    removeChild(c) { this.children = this.children.filter(x => x !== c); c.parentNode = null; },
    addEventListener(ev, fn) { this.listeners[ev] = fn; }, focus() {}, querySelector: () => null};
  created.push(n); return n;
}
const body = node('body'); body.attrs['data-signed-in'] = '1'; body.attrs['data-ai-consent'] = '0';
const calls = [];
global.window = {
  location: {href: 'https://devopsagent.io/chat', origin: 'https://devopsagent.io'},
  fetch: (url, init) => { calls.push([url, init && init.method]);
    if (url === '/api/ai-consent') return Promise.resolve({ok: true, json: () => Promise.resolve({allowed: true})});
    return Promise.resolve({ok: true, status: 200}); },
};
global.Response = class { constructor(b, i) { this.body = b; this.status = i.status; } };
global.document = {
  body, head: node('head'), readyState: 'complete', activeElement: null,
  createElement: node, createTextNode: t => ({textContent: t}),
  getElementById: () => null, addEventListener() {}, removeEventListener() {},
};
%(script)s
function button(cls) { return created.filter(n => n.tag === 'button' && n.attrs['class'] === cls).pop(); }
function open() { return body.children.length > 0; }
(async () => {
  const out = {};
  await window.fetch('/api/chat/history');
  out.getPassed = calls.length === 1;
  let p = window.fetch('/api/chat/stream', {method: 'POST', body: '{}'});
  await new Promise(r => setTimeout(r, 0));
  out.shownOnFirstSend = open();
  out.nothingSentWhileAsking = calls.length === 1;
  button('aic-later').listeners.click();
  const declined = await p;
  out.declinedStatus = declined.status;
  out.closedAfterDecline = !open();
  out.nothingSentAfterDecline = calls.length === 1;
  p = window.fetch('/api/chat', {method: 'POST', body: '{}'});
  await new Promise(r => setTimeout(r, 0));
  button('aic-allow').listeners.click();
  const allowed = await p;
  out.allowedStatus = allowed.status;
  out.calls = calls.map(c => c[0] + ' ' + c[1]);
  out.attr = body.attrs['data-ai-consent'];
  await window.fetch('/api/chat', {method: 'POST'});
  out.noSecondPrompt = !open() && calls.length === 4;
  console.log(JSON.stringify(out));
})();
"""


def test_screen_holds_the_request_until_the_user_answers():
    nodejs = shutil.which('node')
    if not nodejs:
        pytest.skip('node is not installed')
    out = subprocess.run([nodejs, '-e', HARNESS % {'script': SCRIPT}], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout.strip().splitlines()[-1])
    assert r['getPassed']
    assert r['shownOnFirstSend'] and r['nothingSentWhileAsking']
    assert r['declinedStatus'] == 403 and r['closedAfterDecline'] and r['nothingSentAfterDecline']
    assert r['allowedStatus'] == 200
    assert r['calls'][1:3] == ['/api/ai-consent POST', '/api/chat POST'], r['calls']
    assert r['attr'] == '1' and r['noSecondPrompt']


def test_js_screen_covers_every_server_gated_endpoint():
    """The app's consent screen (ai_consent.js) must open for every path the server refuses,
    or the user gets a bare 403 with no way to say yes."""
    import os
    import re
    js = open(os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'ai_consent.js')).read()
    pattern = re.search(r"var AI_PATH = /(.+)/;", js).group(1).replace('\\/', '/')
    for path in AI_ENDPOINTS:
        assert re.match(pattern, path), path
