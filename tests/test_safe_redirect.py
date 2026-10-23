import pytest

from app import app
from routes.auth import _is_safe_redirect


@pytest.mark.parametrize('target,expected', [
    ('/chat', True),
    ('/chat?x=1', True),
    ('http://localhost/chat', True),
    ('//evil.com', False),
    ('http:/evil.com', False),
    ('https:evil.com', False),
    ('/\\evil.com', False),
    ('http://evil.com', False),
    ('javascript:alert(1)', False),
    ('', False),
])
def test_is_safe_redirect(target, expected):
    with app.test_request_context('/login', base_url='http://localhost'):
        assert _is_safe_redirect(target) is expected
