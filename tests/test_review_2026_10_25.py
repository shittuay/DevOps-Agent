from app import app
from routes.auth import _is_safe_redirect
from src.tools.terraform_tools import terraform_apply


def _check(target):
    with app.test_request_context('/', base_url='https://devopsagent.io'):
        return _is_safe_redirect(target)


def test_redirect_rejects_scheme_without_authority():
    for t in ('http:/evil.com', 'https:evil.com', '/\\evil.com', '//evil.com', 'http://evil.com', '/a\nb'):
        assert not _check(t), t


def test_redirect_allows_local_paths():
    assert _check('/dashboard?x=1')
    assert _check('https://devopsagent.io/chat')


def test_terraform_apply_rejects_flag_plan_file():
    assert terraform_apply('/tmp', plan_file='-destroy')['success'] is False
