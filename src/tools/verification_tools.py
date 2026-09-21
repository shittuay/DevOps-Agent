"""Service-reachability probes: is a URL responding, is a TCP port open.

These exist so the agent can *verify* the thing it just built actually works —
"did nginx come up on port 80", "is the load balancer serving 200s yet" — with a
purpose-built tool instead of improvising (a live incident had the agent run
`git clone http://<ip>/` and read the resulting HTTP 404 as success).

Both tools are read-only and SSRF-guarded via `src/utils/network_safety.py`
(`assert_safe_url` / `safe_request` re-validate every redirect hop and strip
auth headers cross-origin; `assert_safe_host` blocks loopback / link-local /
metadata for the raw socket path). They are registered unconditionally and sit
in `ALWAYS_TOOL_NAMES`, so the model can always reach for them.
"""
import socket
import time
from typing import Any, Dict, Optional

from ..utils import get_logger
from ..utils.network_safety import assert_safe_host, assert_safe_url, safe_request, UnsafeUrlError

logger = get_logger(__name__)

_BODY_SNIPPET_CHARS = 500


def http_check(
    url: str,
    method: str = 'GET',
    expected_status: Optional[int] = None,
    timeout: int = 10,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Send one HTTP request and report what came back.

    `reachable` = a response was received at all. `matched_expected` is a
    separate signal, only set when `expected_status` is given — a reachable
    endpoint returning the wrong status (404, 502, ...) is reachable but NOT
    healthy. Redirects are followed (each hop SSRF-revalidated).
    """
    method = (method or 'GET').upper()
    try:
        assert_safe_url(url)
    except UnsafeUrlError as e:
        return {'success': False, 'reachable': False, 'url': url, 'error': str(e),
                'message': f'Refused to probe {url}: {e}'}

    started = time.monotonic()
    try:
        resp = safe_request(method, url, headers=headers or {}, timeout=timeout)
    except UnsafeUrlError as e:
        return {'success': False, 'reachable': False, 'url': url, 'error': str(e),
                'message': f'Refused to follow a redirect from {url}: {e}'}
    except Exception as e:  # noqa: BLE001 — connection refused, timeout, DNS, TLS
        return {'success': True, 'reachable': False, 'url': url, 'error': str(e),
                'message': f'No response from {url}: {e}. The port may be closed/filtered, '
                           f'the host down, or the service not listening.'}

    elapsed_ms = int((time.monotonic() - started) * 1000)
    body = ''
    try:
        body = (resp.text or '')[:_BODY_SNIPPET_CHARS]
    except Exception:  # noqa: BLE001
        pass
    final_url = getattr(resp, 'url', url) or url
    matched = None if expected_status is None else (resp.status_code == expected_status)

    if matched is True:
        msg = f'{url} responded {resp.status_code} as expected in {elapsed_ms}ms.'
    elif matched is False:
        msg = (f'{url} is reachable but responded {resp.status_code}, not the expected '
               f'{expected_status}. The port is open and something is listening, but the '
               f'service is misconfigured, still starting, or serving the wrong content.')
    elif 200 <= resp.status_code < 400:
        msg = f'{url} responded {resp.status_code} in {elapsed_ms}ms.'
    else:
        msg = (f'{url} is reachable but responded {resp.status_code}. The port is open, but a '
               f'{resp.status_code} is not a healthy response — the service is likely '
               f'misconfigured or not ready.')

    return {
        'success': True,
        'reachable': True,
        'url': url,
        'final_url': final_url,
        'redirected': final_url != url,
        'status_code': resp.status_code,
        'matched_expected': matched,
        'response_time_ms': elapsed_ms,
        'server': resp.headers.get('Server'),
        'content_type': resp.headers.get('Content-Type'),
        'body_snippet': body,
        'message': msg,
    }


def tcp_check(host: str, port: int, timeout: int = 5) -> Dict[str, Any]:
    """Attempt a single TCP connection to host:port. Reports only whether the
    port accepts connections — not what protocol speaks there.
    """
    try:
        port = int(port)
    except (TypeError, ValueError):
        return {'success': False, 'open': False, 'host': host, 'port': port,
                'error': 'port must be an integer', 'message': 'port must be an integer'}
    if not 1 <= port <= 65535:
        return {'success': False, 'open': False, 'host': host, 'port': port,
                'error': 'port out of range', 'message': 'port must be between 1 and 65535'}

    try:
        resolved_ip = assert_safe_host(host)
    except UnsafeUrlError as e:
        return {'success': False, 'open': False, 'host': host, 'port': port, 'error': str(e),
                'message': f'Refused to probe {host}:{port}: {e}'}

    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return {
                'success': True, 'open': True, 'host': host, 'port': port,
                'resolved_ip': resolved_ip, 'response_time_ms': elapsed_ms,
                'message': f'{host}:{port} accepted a TCP connection in {elapsed_ms}ms.',
            }
    except socket.timeout:
        return {'success': True, 'open': False, 'host': host, 'port': port,
                'resolved_ip': resolved_ip, 'message': f'{host}:{port} timed out after {timeout}s '
                f'— the port is filtered (firewall/security group dropping packets) or the host is down.'}
    except OSError as e:
        return {'success': True, 'open': False, 'host': host, 'port': port, 'resolved_ip': resolved_ip,
                'error': str(e), 'message': f'{host}:{port} refused the connection ({e}) '
                f'— nothing is listening on that port, or a firewall is rejecting it.'}


def get_tools() -> list:
    return [
        {
            'name': 'http_check',
            'description': (
                'Send one HTTP request to a URL and report the status code, timing, '
                'Server header and a body snippet. Use this to VERIFY a web service is '
                'actually serving (after a deploy, an nginx install, a load-balancer '
                'change). A response means the port is open; a 2xx/3xx (or a match to '
                'expected_status) means it is serving correctly. Never infer HTTP '
                'reachability from another tool\'s error output.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'url': {'type': 'string', 'description': 'Full URL, e.g. http://44.215.109.22/ or https://example.com/health'},
                    'method': {'type': 'string', 'description': 'HTTP method (default GET)', 'default': 'GET'},
                    'expected_status': {'type': 'integer', 'description': 'If given, matched_expected reports whether the status equals this (e.g. 200)'},
                    'timeout': {'type': 'integer', 'description': 'Seconds (default 10)', 'default': 10},
                    'headers': {'type': 'object', 'description': 'Optional request headers'},
                },
                'required': ['url'],
            },
            'handler': http_check,
            'capability': {'permission': 'analyze', 'mutating': False},
        },
        {
            'name': 'tcp_check',
            'description': (
                'Attempt one TCP connection to host:port and report whether the port '
                'accepts connections. Use this to check a non-HTTP port, or to tell '
                '"security group / firewall is blocking the port" (timeout) apart from '
                '"nothing is listening" (connection refused).'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'host': {'type': 'string', 'description': 'Hostname or IP, e.g. 44.215.109.22'},
                    'port': {'type': 'integer', 'description': 'Port number, e.g. 80, 443, 22, 5432'},
                    'timeout': {'type': 'integer', 'description': 'Seconds (default 5)', 'default': 5},
                },
                'required': ['host', 'port'],
            },
            'handler': tcp_check,
            'capability': {'permission': 'analyze', 'mutating': False},
        },
    ]
