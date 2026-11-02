"""The iPhone app shell (mobile/) and the page script that drives its native features
(static/js/native_app.js). The script runs in node with a fake Capacitor bridge."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = (ROOT / 'static' / 'js' / 'native_app.js').read_text()

HARNESS = r"""
const calls = {auth: 0, fetched: [], shared: [], deleted: 0};
let authResult = %(auth)s;
let listeners = {};
function el(cls) { return {classList: {contains: c => c === cls}, querySelectorAll: () => [], querySelector: () => null}; }
global.window = {
  location: {href: 'https://devopsagent.io/chat', pathname: '/chat'},
  localStorage: {data: {}, getItem(k) { return this.data[k] || null; }, setItem(k, v) { this.data[k] = v; }, removeItem(k) { delete this.data[k]; }},
  fetch: (url, init) => { calls.fetched.push([url, init && init.method]); return Promise.resolve({ok: true}); },
  Capacitor: {
    isNativePlatform: () => %(native)s,
    registerPlugin: name => ({
      PushNotifications: {
        addListener: (ev, fn) => { listeners[ev] = fn; },
        checkPermissions: () => Promise.resolve({receive: 'granted'}),
        register: () => Promise.resolve(),
      },
      BiometricAuthNative: {
        checkBiometry: () => Promise.resolve({isAvailable: true, deviceIsSecure: true}),
        internalAuthenticate: () => { calls.auth++; return authResult ? Promise.resolve() : Promise.reject(new Error('cancel')); },
      },
      Share: {share: o => { calls.shared.push(o); return Promise.resolve(); }},
    })[name],
  },
};
global.fetch = window.fetch;
global.Response = class { constructor(body, init) { this.body = body; this.status = init.status; } };
global.URL = URL;
global.MutationObserver = class { observe() {} };
global.document = {
  body: {dataset: {signedIn: '1'}},
  documentElement: {},
  addEventListener: () => {},
  querySelectorAll: () => [],
};
%(script)s
(async () => {
  const before = calls.fetched.length;
  const r1 = await window.fetch('/api/approvals/12/confirm', {method: 'POST'});
  const r2 = await window.fetch('/api/approvals/12/cancel', {method: 'POST'});
  const r3 = await window.fetch('/api/approvals/12/status');
  if (listeners.registration) await listeners.registration({value: 'ab'.repeat(32)});
  if (listeners.registration) await listeners.registration({value: 'ab'.repeat(32)});
  await new Promise(r => setTimeout(r, 10));
  if (listeners.pushNotificationActionPerformed) {
    listeners.pushNotificationActionPerformed({notification: {data: {link: '//evil.example/x'}}});
    const afterEvil = window.location.href;
    listeners.pushNotificationActionPerformed({notification: {data: {link: '/approvals/mine'}}});
    calls.evilHref = afterEvil;
  }
  console.log(JSON.stringify({
    auth: calls.auth, blocked: r1.status === 403,
    fetched: calls.fetched.slice(before), href: window.location.href, evilHref: calls.evilHref,
  }));
})();
"""


def _run(auth=True, native=True):
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    js = HARNESS % {'auth': 'true' if auth else 'false', 'native': 'true' if native else 'false',
                    'script': SCRIPT}
    out = subprocess.run([node, '-e', js], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_face_id_gates_running_an_action_but_not_cancelling():
    res = _run(auth=True)
    assert res['auth'] == 1, 'only the confirm asked for Face ID'
    urls = [u for u, _ in res['fetched']]
    assert '/api/approvals/12/confirm' in urls and '/api/approvals/12/cancel' in urls


def test_cancelled_face_id_sends_nothing():
    res = _run(auth=False)
    assert res['blocked']
    assert '/api/approvals/12/confirm' not in [u for u, _ in res['fetched']]


def test_push_token_sent_once_and_taps_only_open_our_own_pages():
    res = _run()
    posts = [f for f in res['fetched'] if f[0] == '/api/push/devices']
    assert posts == [['/api/push/devices', 'POST']], 'same token twice is sent once'
    assert res['evilHref'] == 'https://devopsagent.io/chat', 'a //host link is ignored'
    assert res['href'] == '/approvals/mine'


def test_does_nothing_in_a_browser():
    res = _run(native=False)
    assert res['auth'] == 0 and res['fetched'][:1] == [['/api/approvals/12/confirm', 'POST']]


def test_script_is_only_loaded_in_the_app_and_logout_is_marked():
    for name in ('base.html', 'index.html'):
        html = (ROOT / 'templates' / name).read_text()
        runtime = "{% if ios_app %}<script src=\"{{ url_for('static', filename='js/vendor/capacitor-8.5.3.js') }}\" defer></script>"
        assert runtime + "<script src=\"{{ url_for('static', filename='js/native_app.js') }}\"" in html, \
            'the Capacitor runtime must load right before native_app.js, in the app only'
        assert 'data-signed-in=' in html
    assert 'data-logout' in (ROOT / 'templates' / 'index.html').read_text()


def test_app_shell_config_matches_the_server():
    from services.app_client import IOS_APP_UA_MARKER
    cfg = json.loads((ROOT / 'mobile' / 'capacitor.config.json').read_text())
    assert cfg['appId'] == 'io.devopsagent.app'
    assert cfg['appendUserAgent'].startswith(IOS_APP_UA_MARKER), 'app mode depends on this marker'
    assert cfg['server']['url'].startswith('https://devopsagent.io/')
    pkg = json.loads((ROOT / 'mobile' / 'package.json').read_text())
    for section in ('dependencies', 'devDependencies'):
        for name, version in pkg[section].items():
            assert version[0].isdigit(), f'{name} must be pinned exactly, got {version}'
    plist = (ROOT / 'mobile' / 'ios' / 'App' / 'App' / 'Info.plist').read_text()
    assert 'NSFaceIDUsageDescription' in plist, 'Face ID crashes without it'
    delegate = (ROOT / 'mobile' / 'ios' / 'App' / 'App' / 'AppDelegate.swift').read_text()
    assert 'capacitorDidRegisterForRemoteNotifications' in delegate
    assert 'aps-environment' in (ROOT / 'mobile' / 'ios' / 'App' / 'App' / 'App.entitlements').read_text()


def test_capacitor_runtime_is_vendored_at_the_app_version_and_adds_register_plugin():
    """iOS injects a bridge without registerPlugin; without the runtime every native feature
    silently turned off (found on the first simulator run, 2026-11-01)."""
    pkg = json.loads((ROOT / 'mobile' / 'package.json').read_text())
    version = pkg['dependencies']['@capacitor/core']
    runtime = ROOT / 'static' / 'js' / 'vendor' / f'capacitor-{version}.js'
    assert runtime.exists(), 'vendor the @capacitor/core runtime matching mobile/package.json'
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    js = ("global.window = globalThis; window.Capacitor = {isNativePlatform: () => true};"
          + runtime.read_text()
          + ";console.log(typeof window.Capacitor.registerPlugin)")
    out = subprocess.run([node, '-e', js], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == 'function'
