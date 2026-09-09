"""Service-reachability probes: http_check, tcp_check, assert_safe_host.

These exist so the agent verifies "is nginx serving on port 80" with a real
tool instead of improvising (a live incident had it run `git clone http://<ip>/`
and read the HTTP 404 as success). Tests cover the SSRF guard, the
reachable-vs-healthy distinction, and cache/selection wiring.
"""
import socket
from unittest.mock import MagicMock, patch

import pytest

from src.utils.network_safety import assert_safe_host, UnsafeUrlError
from src.tools.verification_tools import http_check, tcp_check, get_tools


# --------------------------------------------------------------------------
# assert_safe_host
# --------------------------------------------------------------------------
class TestAssertSafeHost:
    @pytest.mark.parametrize('host', ['127.0.0.1', 'localhost', '169.254.169.254',
                                      'metadata.google.internal', '::1'])
    def test_blocks_loopback_link_local_metadata(self, host):
        with pytest.raises(UnsafeUrlError):
            assert_safe_host(host)

    def test_allows_private_and_public(self):
        # RFC1918 is allowed (self-hosted internal infra), same as assert_safe_url
        assert assert_safe_host('10.0.5.20') == '10.0.5.20'
        ip = assert_safe_host('93.184.216.34')
        assert ip == '93.184.216.34'

    def test_unresolvable_host_raises(self):
        with patch('socket.getaddrinfo', side_effect=socket.gaierror('nodename nor servname')):
            with pytest.raises(UnsafeUrlError):
                assert_safe_host('nope.invalid')

    def test_empty_host_raises(self):
        with pytest.raises(UnsafeUrlError):
            assert_safe_host('')


# --------------------------------------------------------------------------
# http_check
# --------------------------------------------------------------------------
def _resp(status, text='<html>ok</html>', headers=None, url='http://x/'):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.headers = headers or {'Server': 'nginx', 'Content-Type': 'text/html'}
    r.url = url
    return r


class TestHttpCheck:
    def test_200_no_expectation_is_reachable(self):
        with patch('src.tools.verification_tools.safe_request', return_value=_resp(200)):
            out = http_check('http://93.184.216.34/')
        assert out['reachable'] is True
        assert out['status_code'] == 200
        assert out['matched_expected'] is None

    def test_200_matches_expected(self):
        with patch('src.tools.verification_tools.safe_request', return_value=_resp(200)):
            out = http_check('http://93.184.216.34/', expected_status=200)
        assert out['matched_expected'] is True
        assert 'as expected' in out['message']

    def test_404_is_reachable_but_not_healthy(self):
        with patch('src.tools.verification_tools.safe_request', return_value=_resp(404)):
            out = http_check('http://93.184.216.34/', expected_status=200)
        assert out['reachable'] is True
        assert out['matched_expected'] is False
        assert '404' in out['message']
        assert 'not the expected' in out['message'] or 'misconfigured' in out['message']

    def test_502_without_expectation_still_flagged_unhealthy(self):
        with patch('src.tools.verification_tools.safe_request', return_value=_resp(502)):
            out = http_check('http://93.184.216.34/')
        assert out['reachable'] is True
        assert 'not a healthy response' in out['message']

    def test_no_response_is_not_reachable(self):
        with patch('src.tools.verification_tools.safe_request', side_effect=ConnectionError('refused')):
            out = http_check('http://93.184.216.34/')
        assert out['reachable'] is False
        assert out['success'] is True  # the probe itself worked; the target didn't answer

    def test_refuses_blocked_url(self):
        out = http_check('http://169.254.169.254/latest/meta-data/')
        assert out['reachable'] is False
        assert out['success'] is False


# --------------------------------------------------------------------------
# tcp_check
# --------------------------------------------------------------------------
class TestTcpCheck:
    def test_open_port(self):
        with patch('src.tools.verification_tools.assert_safe_host', return_value='93.184.216.34'), \
             patch('socket.create_connection') as cc:
            cc.return_value.__enter__.return_value = MagicMock()
            out = tcp_check('example.com', 80)
        assert out['open'] is True
        assert out['resolved_ip'] == '93.184.216.34'

    def test_refused_port(self):
        with patch('src.tools.verification_tools.assert_safe_host', return_value='93.184.216.34'), \
             patch('socket.create_connection', side_effect=ConnectionRefusedError('refused')):
            out = tcp_check('example.com', 81)
        assert out['open'] is False
        assert 'refused' in out['message'].lower()

    def test_timeout_is_filtered(self):
        with patch('src.tools.verification_tools.assert_safe_host', return_value='93.184.216.34'), \
             patch('socket.create_connection', side_effect=socket.timeout()):
            out = tcp_check('example.com', 80)
        assert out['open'] is False
        assert 'filtered' in out['message'] or 'timed out' in out['message']

    def test_blocked_host_refused(self):
        out = tcp_check('127.0.0.1', 6379)
        assert out['open'] is False
        assert out['success'] is False

    def test_bad_port(self):
        assert tcp_check('example.com', 99999)['success'] is False
        assert tcp_check('example.com', 'nope')['success'] is False


# --------------------------------------------------------------------------
# wiring
# --------------------------------------------------------------------------
class TestWiring:
    def test_tools_declare_read_only_capability(self):
        for t in get_tools():
            assert t['capability']['permission'] == 'analyze'
            assert t['capability']['mutating'] is False

    def test_probes_are_not_cached(self):
        from services.tool_cache import is_read_tool
        assert is_read_tool('http_check') is False
        assert is_read_tool('tcp_check') is False
        assert is_read_tool('run_smoke_test') is False

    def test_probes_always_offered(self):
        from src.agent.tool_selection import ALWAYS_TOOL_NAMES
        assert 'http_check' in ALWAYS_TOOL_NAMES
        assert 'tcp_check' in ALWAYS_TOOL_NAMES

    def test_run_smoke_test_classified_as_verification(self):
        from src.agent.tool_selection import classify_tool
        assert classify_tool('run_smoke_test', 'cicd') == 'verification'

    def test_reachability_message_selects_verification_category(self):
        from src.agent.tool_selection import _explicit_matches
        m = _explicit_matches('is my nginx web server reachable on port 80')
        assert 'verification' in m
