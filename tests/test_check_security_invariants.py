"""Unit tests for scripts/check_security_invariants.py's own detection logic.

Uses synthetic source strings (not the real repo tree) so these are
independent of whatever files currently exist — see
tests/test_security_invariants.py for the test that actually scans the repo.
"""
from scripts.check_security_invariants import (
    _scan_source_for_ssrf,
    _scan_source_for_check_password,
)


class TestSsrfDetection:
    def test_flags_raw_requests_get(self):
        source = (
            "import requests\n"
            "def f(url):\n"
            "    return requests.get(url)\n"
        )
        violations = _scan_source_for_ssrf('fake/module.py', source)
        assert len(violations) == 1
        assert violations[0].line == 3
        assert violations[0].rule == 'ssrf-guard'

    def test_flags_all_http_verbs(self):
        source = (
            "import requests\n"
            "def f(url):\n"
            "    requests.get(url)\n"
            "    requests.post(url)\n"
            "    requests.put(url)\n"
            "    requests.patch(url)\n"
            "    requests.delete(url)\n"
            "    requests.request('GET', url)\n"
        )
        violations = _scan_source_for_ssrf('fake/module.py', source)
        assert len(violations) == 6

    def test_honors_import_alias(self):
        source = (
            "import requests as http_requests\n"
            "def f(url):\n"
            "    return http_requests.post(url)\n"
        )
        violations = _scan_source_for_ssrf('fake/module.py', source)
        assert len(violations) == 1

    def test_exempt_comment_on_same_line_suppresses(self):
        source = (
            "import requests\n"
            "def f(url):\n"
            "    return requests.get(url)  # ssrf-safe: hardcoded test host\n"
        )
        assert _scan_source_for_ssrf('fake/module.py', source) == []

    def test_exempt_comment_on_line_above_suppresses(self):
        source = (
            "import requests\n"
            "def f(url):\n"
            "    # ssrf-safe: hardcoded test host\n"
            "    return requests.get(url)\n"
        )
        assert _scan_source_for_ssrf('fake/module.py', source) == []

    def test_ignores_dict_get_that_is_not_the_requests_module(self):
        """The exact false-positive shape seen in src/tools/kubernetes_tools.py:
        a `.requests` attribute chain ending in `.get(...)`, unrelated to the
        `requests` HTTP library."""
        source = (
            "def f(container):\n"
            "    return container.resources.requests.get('cpu')\n"
        )
        assert _scan_source_for_ssrf('fake/module.py', source) == []

    def test_ignores_files_with_no_requests_import(self):
        source = "def f(url):\n    return some_other_lib.get(url)\n"
        assert _scan_source_for_ssrf('fake/module.py', source) == []

    def test_safe_request_itself_is_not_flagged_as_a_call_it_should_route_through(self):
        """safe_request() legitimately calls requests.request() once —
        that's the implementation of the guard, not a violation. (In the
        real checker this file is additionally skipped entirely via
        SSRF_EXEMPT_FILES; this just confirms the detection logic itself
        doesn't need special-casing beyond that file-level skip.)"""
        source = (
            "import requests\n"
            "def safe_request(method, url, **kwargs):\n"
            "    return requests.request(method, url, **kwargs)\n"
        )
        violations = _scan_source_for_ssrf('fake/module.py', source)
        assert len(violations) == 1  # would be flagged if this file weren't in SSRF_EXEMPT_FILES


class TestCheckPasswordDetection:
    def test_flags_direct_check_password_call(self):
        source = (
            "def login(user, password):\n"
            "    if user.check_password(password):\n"
            "        return True\n"
        )
        violations = _scan_source_for_check_password('fake/routes.py', source)
        assert len(violations) == 1
        assert violations[0].rule == 'check-password-duplication'

    def test_exempt_comment_suppresses(self):
        source = (
            "def login(user, password):\n"
            "    if user.check_password(password):  # check-password-safe: test\n"
            "        return True\n"
        )
        assert _scan_source_for_check_password('fake/routes.py', source) == []

    def test_no_call_no_violation(self):
        source = "def f():\n    pass\n"
        assert _scan_source_for_check_password('fake/routes.py', source) == []
