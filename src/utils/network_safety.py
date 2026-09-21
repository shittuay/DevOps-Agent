"""SSRF guard for tools that make outbound HTTP requests to a caller-supplied URL/host."""
import ipaddress
import socket
from urllib.parse import urlparse, urljoin

import requests

_MAX_REDIRECTS = 5


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


def assert_safe_host(host: str) -> str:
    """
    Validate that `host` (a bare hostname or IP, no scheme) does not resolve to
    a loopback, link-local, multicast or unspecified address — the same SSRF
    policy as `assert_safe_url` but for callers that connect at the socket
    level (e.g. a raw TCP probe) rather than over HTTP.

    Returns the first resolved IP address string. Raises UnsafeUrlError if the
    host is missing, unresolvable, or resolves to a disallowed address.
    """
    if not host or not isinstance(host, str):
        raise UnsafeUrlError("host must be a non-empty string")

    if host.lower() in ('metadata.google.internal',):
        raise UnsafeUrlError(f"Access to {host} is not allowed")

    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise UnsafeUrlError(f"Could not resolve host {host!r}: {e}")

    first_ip = None
    for _, _, _, _, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        if first_ip is None:
            first_ip = ip_str
        if _is_blocked_ip(ip_str):
            raise UnsafeUrlError(
                f"host {host!r} resolves to a disallowed internal/private address ({ip_str})"
            )

    if first_ip is None:
        raise UnsafeUrlError(f"Could not resolve host {host!r}")
    return first_ip


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


def assert_safe_external_webhook_url(url: str) -> str:
    """
    Stricter sibling of assert_safe_url() for arbitrary user-configured
    EXTERNAL webhook endpoints (Slack/Teams/generic outbound webhooks) — a
    different trust model than assert_safe_url's self-hosted-internal-tool
    targets (Jenkins/SonarQube/Nexus/Prometheus/K8s service IPs/etc.), which
    legitimately live on private IPs. Here there is no legitimate reason for
    a notification webhook to target RFC1918/loopback/link-local/reserved
    space, so those ranges are blocked too (not just loopback/link-local).

    Raises UnsafeUrlError if disallowed. Returns the url unchanged if safe.
    """
    if not url or not isinstance(url, str):
        raise UnsafeUrlError("URL must be a non-empty string")

    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise UnsafeUrlError(f"URL scheme must be http or https, got: {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise UnsafeUrlError("URL must include a hostname")

    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise UnsafeUrlError(f"Could not resolve host {hostname!r}: {e}")

    for _, _, _, _, sockaddr in addr_infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved \
                or ip.is_multicast or ip.is_unspecified:
            raise UnsafeUrlError(
                f"Webhook URL host {hostname!r} resolves to a disallowed private/internal address ({sockaddr[0]})"
            )

    return url


_SENSITIVE_HEADERS = ('authorization', 'cookie', 'proxy-authorization')


def _origin(url: str) -> tuple:
    parsed = urlparse(url)
    return (parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80))


def safe_request(
    method: str,
    url: str,
    max_redirects: int = _MAX_REDIRECTS,
    validator=assert_safe_url,
    **kwargs,
) -> requests.Response:
    """
    SSRF-safe drop-in for requests.request()/get()/post()/etc.

    assert_safe_url() only validates the URL you hand it — it has no say over
    what happens next. If the caller then lets `requests` auto-follow
    redirects (the default), a server that passed validation can 302 straight
    to a blocked target (e.g. the cloud metadata endpoint) and `requests`
    will silently follow it, since redirect-following happens inside
    urllib3 with zero knowledge of this app's SSRF policy. This validates
    every hop — the original URL and every `Location` the response points at
    — before connecting to it, and raises UnsafeUrlError instead of
    following anywhere unvalidated.

    `validator` defaults to assert_safe_url but can be swapped for a
    stricter/different policy (must raise on rejection, not return bool) —
    e.g. api_gateway.py's outbound platform webhooks intentionally also block
    RFC1918 (arbitrary user-configured external endpoints, not the
    self-hosted-internal-tool trust model assert_safe_url is designed for),
    and must not have that stricter policy silently loosened on a redirect hop.

    Also drops Authorization/Cookie/Proxy-Authorization headers when a
    redirect crosses to a different origin (scheme+host+port), matching
    `requests`' own built-in cross-origin redirect behavior — otherwise a
    caller-supplied base_url (Grafana/SonarQube/Nexus/etc., typically called
    with a bearer token in headers) that gets redirected to a different host
    would hand that live credential to whatever responded with the redirect.

    Does not address DNS-rebinding (the IP validated here vs. the IP requests
    actually connects to a moment later) — see CLAUDE_RUNBOOK.md.
    """
    kwargs.pop('allow_redirects', None)
    current_url = url
    for _ in range(max_redirects + 1):
        validator(current_url)
        response = requests.request(method, current_url, allow_redirects=False, **kwargs)
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get('Location')
            if not location:
                return response
            next_url = urljoin(current_url, location)
            if _origin(next_url) != _origin(current_url):
                if kwargs.get('headers'):
                    kwargs['headers'] = {
                        k: v for k, v in kwargs['headers'].items()
                        if k.lower() not in _SENSITIVE_HEADERS
                    }
                kwargs.pop('auth', None)  # e.g. Nexus's HTTPBasicAuth tuple
            current_url = next_url
            continue
        return response
    raise UnsafeUrlError(f"Too many redirects (>{max_redirects}) resolving {url!r}")
