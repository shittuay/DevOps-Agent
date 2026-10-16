"""Sandbox must work on its own and give a new user something to do.

A new account that chose "Try it now" got a list of tool categories and was told to
add cloud credentials: the credential status ("NOT configured, do not call these
tools") was injected even in sandbox, and the sandbox switch only showed up once
Learning Mode was on.
"""
import re
from pathlib import Path

import app as app_module

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / 'templates' / 'index.html').read_text()
APP_SRC = (ROOT / 'app.py').read_text()


def test_sandbox_context_does_not_send_user_to_add_credentials():
    ctx = app_module._cloud_access_context(user_id=12345, sandbox_active=True)
    assert 'SANDBOX' in ctx
    assert 'NOT configured' not in ctx
    assert 'Settings > Cloud Credentials' not in ctx


def test_real_mode_still_reports_missing_credentials(monkeypatch):
    import services.credential_service as cs
    monkeypatch.setattr(cs, 'get_user_configured_providers',
                        lambda uid: {'aws': False, 'azure': False, 'gcp': False})
    ctx = app_module._cloud_access_context(user_id=1, sandbox_active=False)
    assert 'NOT configured: AWS, AZURE, GCP' in ctx


def test_both_chat_routes_use_the_sandbox_aware_helper():
    assert APP_SRC.count('_cloud_access_context(current_user.id, sandbox_active)') == 2
    assert APP_SRC.count('CLOUD CREDENTIALS STATUS') == 1  # only inside the helper


def test_sandbox_prompt_offers_missions_not_a_tool_list():
    addendum = app_module.SANDBOX_MODE_ADDENDUM
    assert 'do NOT list tools' in addendum
    assert '$0.042' not in addendum  # prices must be labelled estimates, never facts


def test_sandbox_switch_visible_without_learning_mode():
    row = re.search(r'<div[^>]*id="sandboxRow"[^>]*>', INDEX).group(0)
    assert 'display:none' not in row.replace(' ', '')
    assert "getElementById('sandboxRow').style.display" not in INDEX


def test_turning_learning_off_keeps_sandbox():
    fn = INDEX[INDEX.index('function toggleLearningMode'):INDEX.index('function toggleSandboxMode')]
    assert 'toggleSandboxMode(false)' not in fn


def test_sandbox_welcome_shows_missions():
    assert 'function renderSandboxWelcome' in INDEX
    assert INDEX.count("prompt: \"I'm") == 3
    assert 'renderSandboxWelcome(sb)' in INDEX
