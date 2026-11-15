"""Accessibility basics the 2026-11-10 audit fixed (WCAG 2.1 AA, checked with axe-core on every
page in both themes and in the iPhone app). These are the checks that need no browser, so the
fixes can't quietly come back: contrast of the shared colors, the orange buttons, landmarks,
form labels, closed modals hidden from screen readers, and keyboard access for click targets.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / 'templates'
THEME = (ROOT / 'static' / 'css' / 'theme.css').read_text()
PAGES = sorted(p for p in TEMPLATES.rglob('*.html')
               if '</body>' in p.read_text() and 'email' not in str(p).lower())


def _lum(hex_color):
    h = hex_color.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    rgb = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _vars(block_selector):
    m = re.search(re.escape(block_selector) + r'\s*\{(.*?)\n\}', THEME, re.S)
    assert m, block_selector
    return dict(re.findall(r'(--[\w-]+):\s*(#[0-9a-fA-F]{3,6})\b', m.group(1)))


def test_shared_text_colors_meet_aa_in_both_themes():
    dark = _vars(':root')
    light = {**dark, **_vars('[data-theme="light"]')}
    for name, theme in (('dark', dark), ('light', light)):
        for bg in ('--bg-primary', '--bg-secondary', '--bg-tertiary'):
            for fg in ('--text-primary', '--text-secondary', '--text-tertiary', '--text-muted', '--accent-primary'):
                ratio = contrast(theme[fg], theme[bg])
                assert ratio >= 4.5, f'{name}: {fg} on {bg} is {ratio:.2f}:1'
        ratio = contrast(theme['--on-accent'], theme['--accent-primary'])
        assert ratio >= 4.5, f'{name}: button text on the accent is {ratio:.2f}:1'


ORANGE_BG = re.compile(r'background(?:-color)?\s*:\s*[^;]*(var\(--(?:accent-primary|gradient-primary|orange)(?![-\w])|#ff6b35|#ff4d1c)', re.I)
WHITE_TEXT = re.compile(r'(?<![-\w])color\s*:\s*(white|#fff\b|#ffffff\b)', re.I)


def test_no_white_text_on_the_bright_orange():
    """White on #ff6b35 is 2.8:1. Use var(--on-accent) (dark on the bright orange)."""
    bad = []
    for path in list(TEMPLATES.rglob('*.html')) + list((ROOT / 'static' / 'css').glob('*.css')):
        for block in re.findall(r'\{[^{}]*\}', path.read_text()):
            if ORANGE_BG.search(block) and WHITE_TEXT.search(block):
                bad.append(f'{path.relative_to(ROOT)}: {block[:90]!r}')
    assert not bad, '\n'.join(bad)


def test_every_page_loads_the_keyboard_helper_and_has_a_main_region():
    for page in PAGES:
        html = page.read_text()
        if '{% extends' in html:
            continue
        name = page.relative_to(ROOT)
        assert 'js/a11y.js' in html, f'{name}: missing static/js/a11y.js'
    base = (TEMPLATES / 'base.html').read_text()
    assert 'class="skip-link" href="#main"' in base
    assert '<main class="main-content" id="main"' in base and '<header class="header">' in base
    for name in ('index.html', 'login.html', 'signup.html', 'landing.html', 'privacy-policy.html',
                 'security.html', 'about.html', 'status.html', 'billing.html', 'onboarding.html',
                 'changes.html', 'setup_2fa.html', 'forgot_password.html', 'curriculum/index.html',
                 'curriculum/phase.html', 'infrastructure/map.html', 'drift/dashboard.html'):
        html = (TEMPLATES / name).read_text()
        assert '<main' in html or 'role="main"' in html, f'{name}: no main region'


def test_labels_are_tied_to_their_fields():
    pattern = re.compile(r'<label(?![^>]*\bfor=)[^>]*>[^<]*</label>\s*<(input|select|textarea)\b[^>]*\b(id|name)=')
    bad = [f'{p.relative_to(ROOT)}: {m.group(0)[:80]!r}'
           for p in TEMPLATES.rglob('*.html') for m in pattern.finditer(p.read_text())]
    assert not bad, '\n'.join(bad)


def test_closed_modals_are_hidden_not_just_transparent():
    """opacity:0 alone leaves a closed modal readable by screen readers and reachable with Tab."""
    bad = []
    for path in TEMPLATES.rglob('*.html'):
        for m in re.finditer(r'([^{}]+)\{([^{}]*)\}', path.read_text()):
            selector, body = m.group(1).strip(), m.group(2)
            if not re.search(r'modal-overlay|notif-panel', selector) or '.open' in selector or '.active' in selector:
                continue
            if re.search(r'opacity\s*:\s*0\s*;', body) and 'pointer-events: none' in body and 'visibility: hidden' not in body:
                bad.append(f'{path.relative_to(ROOT)}: {selector[-50:]}')
    assert not bad, '\n'.join(bad)


def test_chat_announces_replies_without_reading_every_streamed_word():
    chat = (TEMPLATES / 'index.html').read_text()
    assert 'id="replyAnnouncer" role="status" aria-live="polite"' in chat
    assert 'role="log"' not in chat and 'id="chatContainer" role="region"' in chat
    assert 'aria-label="Open sessions menu"' in chat
    assert 'role="alertdialog"' in chat, 'the risky-action confirmation must be a labelled dialog'


HARNESS = r"""
const made = [];
function node(tag, onclick, cls) {
  const n = {tagName: tag, nodeType: 1, attrs: onclick ? {onclick} : {}, className: cls || '', listeners: {}, clicked: 0,
    hasAttribute(k) { return k in this.attrs; }, getAttribute(k) { return this.attrs[k] ?? null; },
    setAttribute(k, v) { this.attrs[k] = v; }, addEventListener(e, f) { this.listeners[e] = f; },
    click() { this.clicked++; }, querySelectorAll() { return []; }};
  made.push(n); return n;
}
const div = node('DIV', "doThing()"), nav = node('DIV', "window.location.href='/x'"),
      btn = node('BUTTON', "go()"), overlay = node('DIV', 'close()', 'modal-overlay'),
      stop = node('DIV', 'event.stopPropagation()');
const body = Object.assign(node('BODY'), {querySelectorAll: () => [div, nav, btn, overlay, stop]});
global.document = {readyState: 'complete', body, addEventListener() {}};
global.MutationObserver = class { observe() {} };
%(script)s
const key = (el, k) => { const e = {key: k, target: el, prevented: false, preventDefault() { this.prevented = true; }}; el.listeners.keydown(e); return e; };
key(div, 'Enter'); key(div, ' '); key(nav, 'Enter'); key(nav, ' ');
console.log(JSON.stringify({
  div: [div.attrs.role, div.attrs.tabindex, div.clicked], nav: [nav.attrs.role, nav.clicked],
  untouched: [btn, overlay, stop].map(n => n.attrs.role || n.attrs.tabindex || null),
}));
"""


def test_keyboard_helper_makes_click_targets_operable():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    script = (ROOT / 'static' / 'js' / 'a11y.js').read_text()
    out = subprocess.run([node, '-e', HARNESS % {'script': script}], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout.strip().splitlines()[-1])
    assert r['div'] == ['button', '0', 2]
    assert r['nav'] == ['link', 1], 'links open with Enter only, as in the browser'
    assert r['untouched'] == [None, None, None]
