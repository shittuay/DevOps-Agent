"""
Shared SSRF guard for tools/services that make outbound HTTP requests to
user-supplied URLs (webhook targets, base_url params, health-check URLs).

Blocks non-http(s) schemes and any hostname that resolves to a private,
loopback, link-local, or otherwise reserved IP range (including cloud
metadata endpoints like 169.254.169.254).
"""
import ipaddress
import socket
from urllib.parse import urlparse


def is_safe_external_url(url: str) -> bool:
    """Return True only if url is http(s) and resolves exclusively to public IPs.

    Use for integrations with a fixed/known-external service (webhooks,
    SonarQube, Nexus, Jenkins, GitLab base_url params) where an internal
    target is never legitimate.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        resolved = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in resolved:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except Exception:
        return False


def is_safe_probe_url(url: str) -> bool:
    """Return True if url is http(s) and does not resolve to loopback/link-local/
    reserved/multicast addresses. Unlike is_safe_external_url, private (RFC1918)
    ranges are allowed — deployment smoke tests and rollback health checks
    legitimately target internal cluster/VPC service addresses. This still
    blocks 127.0.0.1 (the app host itself) and 169.254.169.254 (cloud metadata).
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        resolved = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in resolved:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except Exception:
        return False


SSRF_BLOCKED_MESSAGE = "URL targets a private/internal network or is not http(s) (blocked by SSRF protection)"
