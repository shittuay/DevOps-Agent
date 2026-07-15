"""
Regression tests for the SSRF guard (src/utils/network_safety.py) used by
tool modules that accept a caller-supplied URL/host (SonarQube, Nexus,
Prometheus, Grafana, Jenkins, run_smoke_test, auto_rollback_deployment).
"""
import pytest

from src.utils.network_safety import assert_safe_url, UnsafeUrlError


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
