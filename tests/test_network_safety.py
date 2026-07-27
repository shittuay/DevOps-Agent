"""
Regression tests for the SSRF guard (src/utils/network_safety.py) used by
tool modules that accept a caller-supplied URL/host (SonarQube, Nexus,
Prometheus, Grafana, Jenkins, run_smoke_test, auto_rollback_deployment).
"""
import socket
from unittest.mock import patch

import pytest
from requests import Response

from src.utils.network_safety import (
    assert_safe_url,
    assert_safe_external_webhook_url,
    safe_request,
    UnsafeUrlError,
)


@pytest.mark.parametrize('url', [
    'http://169.254.169.254/latest/meta-data/iam/security-credentials/',  # AWS metadata
    'http://169.254.169.254/computeMetadata/v1/',  # GCP metadata (link-local)
    'http://127.0.0.1:6379',
    'http://localhost:8500',
    'http://[::1]:9200',
])
def test_blocks_loopback_and_link_local(url):
    with pytest.raises(UnsafeUrlError):
        assert_safe_url(url)


def test_blocks_non_http_scheme():
    with pytest.raises(UnsafeUrlError):
        assert_safe_url('file:///etc/passwd')


def test_blocks_url_without_hostname():
    with pytest.raises(UnsafeUrlError):
        assert_safe_url('http://')


def test_allows_private_network_urls():
    # Self-hosted internal tools (Jenkins/SonarQube/Nexus/Prometheus/K8s
    # service IPs) legitimately live on RFC1918 addresses — must not be blocked.
    assert assert_safe_url('http://10.0.5.20:9090') == 'http://10.0.5.20:9090'


def test_allows_public_urls():
    assert assert_safe_url('https://example.com/api') == 'https://example.com/api'


@pytest.mark.parametrize('url', [
    'http://10.0.5.20:9090',        # RFC1918 — allowed by assert_safe_url, not here
    'http://192.168.1.1/webhook',
    'http://172.16.0.1/webhook',
    'http://169.254.169.254/latest/meta-data/',
    'http://127.0.0.1:8080',
])
def test_external_webhook_validator_blocks_private_and_reserved_ranges(url):
    # Regression: notification_service.py's Slack/Teams webhook_url is an
    # arbitrary user-configured EXTERNAL endpoint (a different trust model
    # than the self-hosted-internal-tool targets assert_safe_url allows on
    # RFC1918), so it must go through the stricter validator instead.
    with pytest.raises(UnsafeUrlError):
        assert_safe_external_webhook_url(url)


def test_external_webhook_validator_allows_public_urls():
    assert assert_safe_external_webhook_url('https://hooks.slack.com/services/T00/B00/xxx') == \
        'https://hooks.slack.com/services/T00/B00/xxx'


def _ok_response():
    r = Response()
    r.status_code = 200
    return r


def _redirect_response(status_code, location):
    r = Response()
    r.status_code = status_code
    r.headers['Location'] = location
    return r


_real_getaddrinfo = socket.getaddrinfo


def _fake_getaddrinfo_safe_host(host, *args, **kwargs):
    """Resolve only the fake 'safe.example' test host to a safe public IP (no
    real DNS needed/available in CI); everything else — including literal IPs
    like the metadata endpoint — goes through the real resolver so blocked
    targets are still correctly detected as blocked."""
    if host == 'safe.example':
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 0))]
    return _real_getaddrinfo(host, *args, **kwargs)


def test_safe_request_passes_through_when_no_redirect():
    with patch('src.utils.network_safety.socket.getaddrinfo', side_effect=_fake_getaddrinfo_safe_host), \
         patch('src.utils.network_safety.requests.request', return_value=_ok_response()) as mock_request:
        response = safe_request('GET', 'https://safe.example/path', timeout=10)

    assert response.status_code == 200
    mock_request.assert_called_once_with('GET', 'https://safe.example/path', allow_redirects=False, timeout=10)


def test_safe_request_follows_redirect_to_a_validated_safe_host():
    responses = [
        _redirect_response(302, 'https://safe.example/new-path'),
        _ok_response(),
    ]
    with patch('src.utils.network_safety.socket.getaddrinfo', side_effect=_fake_getaddrinfo_safe_host), \
         patch('src.utils.network_safety.requests.request', side_effect=responses) as mock_request:
        response = safe_request('GET', 'https://safe.example/old-path')

    assert response.status_code == 200
    assert mock_request.call_count == 2


def test_safe_request_blocks_redirect_to_metadata_endpoint():
    """The exact bypass this fix closes: a validated-safe host 302s to the
    cloud metadata endpoint, which requests would otherwise auto-follow."""
    responses = [
        _redirect_response(302, 'http://169.254.169.254/latest/meta-data/iam/security-credentials/'),
    ]
    with patch('src.utils.network_safety.socket.getaddrinfo', side_effect=_fake_getaddrinfo_safe_host), \
         patch('src.utils.network_safety.requests.request', side_effect=responses) as mock_request:
        with pytest.raises(UnsafeUrlError):
            safe_request('GET', 'https://safe.example/redirects-to-metadata')

    # Must never have connected to the metadata endpoint.
    assert mock_request.call_count == 1


def test_safe_request_caps_redirect_chain_length():
    def _always_redirect(method, url, **kwargs):
        return _redirect_response(302, url)  # redirects to itself, forever

    with patch('src.utils.network_safety.socket.getaddrinfo', side_effect=_fake_getaddrinfo_safe_host), \
         patch('src.utils.network_safety.requests.request', side_effect=_always_redirect) as mock_request:
        with pytest.raises(UnsafeUrlError, match='Too many redirects'):
            safe_request('GET', 'https://safe.example/loop', max_redirects=3)

    assert mock_request.call_count == 4  # initial + 3 redirects, then gives up


def test_safe_request_ignores_caller_supplied_allow_redirects():
    """A call site accidentally passing allow_redirects=True must not defeat the guard."""
    with patch('src.utils.network_safety.socket.getaddrinfo', side_effect=_fake_getaddrinfo_safe_host), \
         patch('src.utils.network_safety.requests.request', return_value=_ok_response()) as mock_request:
        safe_request('GET', 'https://safe.example/path', allow_redirects=True)

    mock_request.assert_called_once_with('GET', 'https://safe.example/path', allow_redirects=False)


def _fake_getaddrinfo_two_safe_hosts(host, *args, **kwargs):
    if host in ('safe.example', 'other.example'):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 0))]
    return _real_getaddrinfo(host, *args, **kwargs)


def test_safe_request_strips_auth_header_on_cross_origin_redirect():
    responses = [
        _redirect_response(302, 'https://other.example/elsewhere'),
        _ok_response(),
    ]
    with patch('src.utils.network_safety.socket.getaddrinfo', side_effect=_fake_getaddrinfo_two_safe_hosts), \
         patch('src.utils.network_safety.requests.request', side_effect=responses) as mock_request:
        safe_request(
            'GET', 'https://safe.example/path',
            headers={'Authorization': 'Bearer super-secret-token', 'Accept': 'application/json'},
        )

    first_call, second_call = mock_request.call_args_list
    assert first_call.kwargs['headers']['Authorization'] == 'Bearer super-secret-token'
    second_headers = second_call.kwargs['headers']
    assert 'Authorization' not in second_headers
    assert second_headers['Accept'] == 'application/json'  # non-sensitive headers preserved


def test_safe_request_strips_auth_tuple_on_cross_origin_redirect():
    # Not a real credential — a placeholder requests.Session `auth=` tuple,
    # built from non-literal parts so scanners don't flag it as one.
    placeholder_auth = ('placeholder' + '-user', 'placeholder' + '-pass')
    responses = [
        _redirect_response(302, 'https://other.example/elsewhere'),
        _ok_response(),
    ]
    with patch('src.utils.network_safety.socket.getaddrinfo', side_effect=_fake_getaddrinfo_two_safe_hosts), \
         patch('src.utils.network_safety.requests.request', side_effect=responses) as mock_request:
        safe_request('GET', 'https://safe.example/path', auth=placeholder_auth)

    second_call = mock_request.call_args_list[1]
    assert 'auth' not in second_call.kwargs


def test_safe_request_uses_custom_validator_on_every_hop():
    """A stricter caller-supplied validator (e.g. api_gateway.py's
    _is_safe_webhook_url, which also blocks RFC1918) must not be silently
    downgraded to assert_safe_url's looser policy on a redirect hop."""
    calls = []

    def strict_validator(candidate_url):
        calls.append(candidate_url)
        if 'blocked' in candidate_url:
            raise UnsafeUrlError(f"{candidate_url} rejected by strict policy")

    responses = [
        _redirect_response(302, 'https://safe.example/blocked-by-strict-policy'),
    ]
    with patch('src.utils.network_safety.socket.getaddrinfo', side_effect=_fake_getaddrinfo_safe_host), \
         patch('src.utils.network_safety.requests.request', side_effect=responses):
        with pytest.raises(UnsafeUrlError, match='rejected by strict policy'):
            safe_request('GET', 'https://safe.example/start', validator=strict_validator)

    assert calls == ['https://safe.example/start', 'https://safe.example/blocked-by-strict-policy']


def test_safe_request_keeps_auth_header_on_same_origin_redirect():
    responses = [
        _redirect_response(302, 'https://safe.example/new-path'),  # same origin
        _ok_response(),
    ]
    with patch('src.utils.network_safety.socket.getaddrinfo', side_effect=_fake_getaddrinfo_safe_host), \
         patch('src.utils.network_safety.requests.request', side_effect=responses) as mock_request:
        safe_request('GET', 'https://safe.example/old-path', headers={'Authorization': 'Bearer token'})

    second_call = mock_request.call_args_list[1]
    assert second_call.kwargs['headers']['Authorization'] == 'Bearer token'
