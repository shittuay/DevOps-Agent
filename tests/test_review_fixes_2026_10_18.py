"""Pins the 2026-10-18 review fixes: GitHub path validation, MFA reset, contact form escaping."""
import pytest

from src.tools import cicd_tools


@pytest.mark.parametrize('bad', ['../orgs', 'a/b', '..', '.', '', 'a b', 'x?y'])
def test_gh_segment_rejects_path_tricks(bad):
    with pytest.raises(ValueError):
        cicd_tools._gh_segment(bad, 'repo_name')


def test_gh_segment_accepts_normal_names():
    assert cicd_tools._gh_segment('my-repo_1.x', 'repo_name') == 'my-repo_1.x'


def test_github_tool_refuses_traversal_without_network(monkeypatch):
    monkeypatch.setattr(cicd_tools, '_get_github_token', lambda t=None: 'tok')
    called = []
    monkeypatch.setattr(cicd_tools.requests, 'post', lambda *a, **k: called.append(1))
    result = cicd_tools.cancel_github_workflow_run('o', '../../orgs/x', 1)
    assert result['success'] is False and not called


def test_github_calls_set_timeout(monkeypatch):
    monkeypatch.setattr(cicd_tools, '_get_github_token', lambda t=None: 'tok')
    seen = {}

    class R:
        status_code = 202
        text = ''

    def fake_post(url, **kw):
        seen.update(kw)
        return R()

    monkeypatch.setattr(cicd_tools.requests, 'post', fake_post)
    assert cicd_tools.cancel_github_workflow_run('o', 'r', 5)['success'] is True
    assert seen['timeout'] == cicd_tools.GITHUB_API_TIMEOUT


def test_reset_mfa_does_not_log_in_and_contact_escapes():
    import inspect
    from routes import auth
    src = inspect.getsource(auth.reset_mfa)
    assert 'login_user(' not in src
    import app as app_module
    contact = inspect.getsource(app_module.submit_contact)
    assert 'html_escape(message)' in contact and '{message}' not in contact.split('_wrap_html')[1]
