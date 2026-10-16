"""The light/dark switch lives in the profile menu, not floating over the page.

Before: base.html and the chat page put a moon/sun pill in the header, and theme.js
injected a fixed pill at top: 80px; right: 20px on every page without one, covering
headings and buttons. Now signed-in pages carry a "Theme: Light / Dark" row in the
profile menu, and pages with no profile menu get a small switch in the bottom-left corner.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = (ROOT / 'templates' / 'base.html').read_text()
CHAT = (ROOT / 'templates' / 'index.html').read_text()
THEME_JS = (ROOT / 'static' / 'js' / 'theme.js').read_text()
THEME_CSS = (ROOT / 'static' / 'css' / 'theme.css').read_text()


def _theme_row(menu):
    start = menu.index('data-theme-menu')
    return menu[start:menu.index('</div>', start)]


def _base_menu():
    start = BASE.index('id="accountMenuList"')
    return BASE[start:BASE.index('account-menu-logout', start)]


def _chat_menu():
    start = CHAT.index('<div class="dropdown" id="mainMenu">')
    return CHAT[start:CHAT.index("window.location.href='/logout'", start)]


def test_no_toggle_in_either_header():
    assert 'class="theme-toggle' not in BASE
    assert not re.search(r'<div class="theme-toggle', CHAT)


def test_both_profile_menus_have_light_and_dark():
    for menu in (_base_menu(), _chat_menu()):
        row = _theme_row(menu)
        assert 'class="theme-choice-btn" data-theme="light"' in row
        assert 'class="theme-choice-btn" data-theme="dark"' in row


def test_menu_buttons_switch_the_theme():
    assert ".closest('.theme-toggle-btn, .theme-choice-btn')" in THEME_JS
    assert "querySelectorAll('.theme-toggle-btn, .theme-choice-btn')" in THEME_JS
    # the chat page binds its own handler too
    assert CHAT.count("querySelectorAll('.theme-toggle-btn, .theme-choice-btn')") == 2


def test_no_floating_switch_where_the_menu_has_one():
    assert "document.querySelector('.theme-toggle, [data-theme-menu]')" in THEME_JS


def test_leftover_floating_switch_sits_bottom_left():
    assert "toggle.className = 'theme-toggle theme-toggle-floating'" in THEME_JS
    rule = THEME_CSS[THEME_CSS.index('.theme-toggle.theme-toggle-floating {'):]
    rule = rule[:rule.index('}')]
    assert 'bottom: 16px' in rule and 'left: 16px' in rule
    assert 'top: auto' in rule and 'right: auto' in rule
    # the phone rule must not move it back to the right
    assert '.theme-toggle:not(.theme-toggle-floating) {' in THEME_CSS


def test_settings_page_renders_the_theme_row(authenticated_client):
    html = authenticated_client.get('/settings').get_data(as_text=True)
    assert 'data-theme-menu' in html
    assert 'theme-choice-btn' in html
