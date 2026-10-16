"""The AWS self-grant option on Settings must not inherit the page-wide form styles.

The page styles every ``label`` as uppercase monospace and every ``input`` as
``width: 100%``. Inside the Current Configuration box that turned the checkbox
into a wide white bar and the description into shouting capitals, and the long
role ARN pushed the page wider than a phone.
"""
import re
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / 'templates' / 'settings.html').read_text()


def _css_block(selector: str) -> str:
    match = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', HTML)
    assert match, f'missing CSS block for {selector}'
    return match.group(1)


def test_self_grant_label_uses_its_own_class():
    assert '<label class="self-grant-option">' in HTML
    assert 'id="selfGrantToggle" onchange="setSelfGrant(this.checked)" />' in HTML


def test_self_grant_label_is_not_uppercase_monospace():
    css = _css_block('.self-grant-option')
    assert 'text-transform: none' in css
    assert "'Outfit'" in css


def test_self_grant_checkbox_is_checkbox_sized():
    css = _css_block('.self-grant-option input[type="checkbox"]')
    assert 'width: 18px' in css
    assert 'flex-shrink: 0' in css


def test_long_identity_wraps_on_a_phone():
    assert 'overflow-wrap: anywhere' in _css_block('.current-config p')
