"""Settings live in one place, reached from the profile menu.

Before: a Settings tab in the top bar, a separate /profile page (name, appearance, two-factor),
a /settings/skills page nothing linked to, and Profile / Settings / Notifications as three
separate profile-menu entries.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'templates'
BASE = (TEMPLATES / 'base.html').read_text()
CHAT = (TEMPLATES / 'index.html').read_text()
SETTINGS = (TEMPLATES / 'settings.html').read_text()


def _chat_header_nav():
    start = CHAT.index('<nav class="header-nav">')
    return CHAT[start:CHAT.index('</nav>', start)]


def _chat_profile_menu():
    start = CHAT.index('<div class="dropdown" id="mainMenu">')
    return CHAT[start:CHAT.index("window.location.href='/logout'", start)]


# --- navigation -------------------------------------------------------------------

def test_settings_is_not_a_top_bar_tab():
    header_links = re.findall(r'<a href="([^"]+)" class="header-button', BASE)
    assert '/settings' not in header_links
    assert '/settings' not in _chat_header_nav()


def test_app_shell_profile_icon_opens_a_menu_with_settings():
    start = BASE.index('id="accountMenu"')
    menu = BASE[start:BASE.index('account-menu-logout', start) + 200]
    for href in ('/settings', '/billing', '/organizations/', '/logout'):
        assert f'href="{href}"' in menu, href
    assert 'aria-expanded="false"' in menu
    assert "e.key === 'Escape'" in BASE


def test_chat_profile_menu_has_one_settings_entry():
    menu = _chat_profile_menu()
    assert menu.count("window.location.href='/settings'") == 1
    assert "/profile'" not in menu
    assert "/settings#notifications'" not in menu
    assert '{{ current_user.email }}' in menu


def test_nothing_links_to_the_old_pages():
    offenders = []
    for path in TEMPLATES.rglob('*.html'):
        text = path.read_text()
        if re.search(r'href=["\']/profile["\'#]', text) or "'/profile'" in text or '/settings/skills' in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, offenders


# --- the settings page --------------------------------------------------------------

def test_every_tab_has_a_panel_and_is_valid():
    tabs = re.findall(r'data-tab="([a-z-]+)"', SETTINGS)
    panels = set(re.findall(r'data-tab-panel="([a-z-]+)"', SETTINGS))
    valid = re.search(r"const validTabs = \[([^\]]+)\]", SETTINGS).group(1)
    valid = set(re.findall(r"'([a-z-]+)'", valid))
    assert tabs[0] == 'profile'
    for tab in ('profile', 'security', 'cloud', 'integrations', 'notifications', 'budgets', 'learning', 'skills', 'api-keys'):
        assert tab in tabs and tab in panels and tab in valid, tab
    assert "tab = 'profile'" in SETTINGS


def test_billing_and_teams_are_in_the_tab_row():
    nav = SETTINGS[SETTINGS.index('<nav class="settings-tabs"'):SETTINGS.index('</nav>', SETTINGS.index('<nav class="settings-tabs"'))]
    assert 'href="/billing"' in nav and 'href="/organizations/"' in nav


def test_profile_form_posts_with_csrf():
    form = SETTINGS[SETTINGS.index('<form method="POST" action="/profile">'):]
    form = form[:form.index('</form>')]
    assert 'name="csrf_token"' in form
    for field in ('full_name', 'bio', 'avatar_color', 'theme'):
        assert f'name="{field}"' in form


def test_skills_panel_does_not_restyle_settings():
    panel = (TEMPLATES / 'settings' / '_skills_panel.html').read_text()
    for generic in ('    .section {', '.section-title', '.empty {', 'function escapeHtml'):
        assert generic not in panel, generic


def test_settings_page_renders_every_tab(authenticated_client, test_user, db_session):
    test_user.full_name = 'Ada Lovelace'
    db_session.commit()
    resp = authenticated_client.get('/settings')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'value="Ada Lovelace"' in html
    assert 'Two-factor sign-in' in html
    assert 'id="skills-grid"' in html


# --- old addresses still work ----------------------------------------------------------

def test_profile_get_redirects_to_settings(authenticated_client):
    resp = authenticated_client.get('/profile')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/settings#profile')


def test_skills_page_redirects_to_settings(authenticated_client):
    resp = authenticated_client.get('/settings/skills')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/settings#skills')


def test_profile_save_redirects_back_to_settings(authenticated_client, test_user, db_session):
    page = authenticated_client.get('/settings').get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    resp = authenticated_client.post('/profile', data={
        'csrf_token': token, 'full_name': 'Grace Hopper', 'bio': 'hi',
        'avatar_color': 'javascript:alert(1)', 'theme': 'neon',
    })
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/settings?saved=profile#profile')
    db_session.refresh(test_user)
    assert test_user.full_name == 'Grace Hopper'
    assert test_user.avatar_color != 'javascript:alert(1)'
    assert test_user.theme in ('light', 'dark', None)
