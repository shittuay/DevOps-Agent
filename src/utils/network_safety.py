"""SSRF guard for tools that make outbound HTTP requests to a caller-supplied URL/host."""
import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeUrlError(ValueError):
    """Raised when a URL resolves to a disallowed (internal/link-local) host."""


def _is_blocked_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparsable — treat as unsafe
    # Note: RFC1918 private ranges are deliberately NOT blocked here — these
    # tools are designed to reach self-hosted internal infra (Jenkins,
    # SonarQube, Nexus, Prometheus, Grafana, K8s service IPs), which almost
    # always lives on a private IP. Blocking is_private would break that
    # legitimate, intended use. We block only targets that are never a
    # legitimate configured target: the cloud metadata service (link-local),
    # loopback (the app server's own local-only services), and multicast/
    # unspecified addresses.
    return (
        ip.is_loopback
        or ip.is_link_local  # covers 169.254.0.0/16 (cloud metadata) and fe80::/10
        or ip.is_multicast
        or ip.is_unspecified
    )


def assert_safe_url(url: str) -> str:
    """
    Validate that `url` is http(s) and does not resolve to a loopback,
    link-local, or other always-illegitimate address (blocks SSRF to cloud
    metadata endpoints and services bound to the app server's own loopback
    interface). Returns the url unchanged if safe.

    Raises UnsafeUrlError if the URL is disallowed.
    """
    if not url or not isinstance(url, str):
        raise UnsafeUrlError("URL must be a non-empty string")

    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise UnsafeUrlError(f"URL scheme must be http or https, got: {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise UnsafeUrlError("URL must include a hostname")

    if hostname.lower() in ('metadata.google.internal',):
        raise UnsafeUrlError(f"Access to {hostname} is not allowed")

    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise UnsafeUrlError(f"Could not resolve host {hostname!r}: {e}")

    for family, _, _, _, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        if _is_blocked_ip(ip_str):
            raise UnsafeUrlError(
                f"URL host {hostname!r} resolves to a disallowed internal/private address ({ip_str})"
            )

    return url
