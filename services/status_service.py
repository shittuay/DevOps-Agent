"""
Public status page checks.

Until 2026-10-14 most of these only checked that an environment variable was set
("AI inference available" whenever an API key existed), and a "Get notified" box
took email sign-ups that nothing ever emailed. Now each service is actually
probed, the results are cached for CACHE_SECONDS so a public page can't hammer
the providers, and the sign-up is gone. Existing subscribers can still use their
unsubscribe link.

Details shown publicly are fixed phrases, never exception text.
"""
import logging
import os
import smtplib
import threading
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from src.utils.timeutils import utcnow

logger = logging.getLogger(__name__)

CACHE_SECONDS = 120
_TIMEOUT = 5

_SERVICES = [
    {'key': 'api',     'name': 'API',       'description': 'Core REST API and chat endpoints'},
    {'key': 'db',      'name': 'Database',  'description': 'Accounts, conversations and settings'},
    {'key': 'ai',      'name': 'AI / Chat', 'description': 'Kimi and Claude model providers'},
    {'key': 'billing', 'name': 'Billing',   'description': 'Stripe payments and subscriptions'},
    {'key': 'email',   'name': 'Email',     'description': 'Sign-in codes and notification email'},
]

_STATUS_COLORS = {
    'operational': '#22c55e',
    'degraded':    '#f59e0b',
    'outage':      '#ef4444',
    'unknown':     '#6b7280',
}

_STATUS_LABELS = {
    'operational': 'Operational',
    'degraded':    'Degraded Performance',
    'outage':      'Service Outage',
    'unknown':     'Unknown',
}

Check = Tuple[str, str]


def _http_status(url: str, headers: Optional[Dict] = None, auth=None) -> Optional[int]:
    """HTTP status of a GET to a fixed provider URL, or None if unreachable."""
    from src.utils.network_safety import safe_request
    try:
        return safe_request('GET', url, headers=headers or {}, auth=auth, timeout=_TIMEOUT).status_code
    except Exception as e:
        logger.info(f'Status probe failed for {url.split("/")[2]}: {type(e).__name__}')
        return None


def _from_http(code: Optional[int], name: str) -> Check:
    if code is None:
        return 'outage', f'{name} unreachable'
    if code in (401, 403):
        return 'outage', f'{name} rejected our credentials'
    if code >= 500:
        return 'degraded', f'{name} returned an error'
    return 'operational', f'{name} responding'  # 2xx, 3xx, 404, 429: the service is up


class StatusService:
    def __init__(self):
        self._app = None
        self._email_service = None
        self._lock = threading.Lock()
        self._cache: Optional[Tuple[float, List[Dict], datetime]] = None

    def set_app(self, app):
        self._app = app

    def set_email_service(self, email_service):
        self._email_service = email_service

    # ------------------------------------------------------------------
    # Health checks
    # ------------------------------------------------------------------

    def check_health(self, force: bool = False) -> List[Dict]:
        """Status of every service, cached for CACHE_SECONDS."""
        with self._lock:
            if not force and self._cache and time.monotonic() - self._cache[0] < CACHE_SECONDS:
                return self._cache[1]
            results = []
            for svc in _SERVICES:
                checker: Callable[[], Check] = getattr(self, f'_check_{svc["key"]}')
                try:
                    status, detail = checker()
                except Exception as e:
                    logger.warning(f'Status check {svc["key"]} crashed: {e}')
                    status, detail = 'unknown', 'Check could not run'
                results.append({
                    'key':         svc['key'],
                    'name':        svc['name'],
                    'description': svc['description'],
                    'status':      status,
                    'detail':      detail,
                    'color':       _STATUS_COLORS.get(status, _STATUS_COLORS['unknown']),
                    'label':       _STATUS_LABELS.get(status, 'Unknown'),
                })
            self._cache = (time.monotonic(), results, utcnow())
            return results

    def checked_at(self) -> Optional[datetime]:
        """When the cached results were produced (UTC, naive)."""
        return self._cache[2] if self._cache else None

    def get_overall_status(self, service_results=None):
        """Derive overall platform status from individual service checks."""
        if service_results is None:
            service_results = self.check_health()
        statuses = [s['status'] for s in service_results]
        if 'outage' in statuses:
            return 'outage'
        if 'degraded' in statuses:
            return 'degraded'
        if all(s == 'operational' for s in statuses):
            return 'operational'
        return 'unknown'

    def _check_api(self) -> Check:
        if not self._app:
            return 'unknown', 'App not initialised'
        return 'operational', 'Serving requests'  # this check runs inside a served request

    def _check_db(self) -> Check:
        if not self._app:
            return 'unknown', 'App not initialised'
        try:
            with self._app.app_context():
                from models import db
                db.session.execute(db.text('SELECT 1'))
            return 'operational', 'Database reachable'
        except Exception as e:
            logger.warning(f'DB health check failed: {e}')
            return 'outage', 'Database unreachable'

    def _check_ai(self) -> Check:
        probes = []
        if os.getenv('MOONSHOT_API_KEY'):
            probes.append(_from_http(_http_status(
                'https://api.moonshot.ai/v1/models',
                headers={'Authorization': f'Bearer {os.getenv("MOONSHOT_API_KEY")}'}), 'Kimi'))
        if os.getenv('ANTHROPIC_API_KEY'):
            probes.append(_from_http(_http_status(
                'https://api.anthropic.com/v1/models',
                headers={'x-api-key': os.getenv('ANTHROPIC_API_KEY'),
                         'anthropic-version': '2023-06-01'}), 'Claude'))
        if not probes:
            return 'outage', 'No model provider configured'
        ok = [p for p in probes if p[0] == 'operational']
        if len(ok) == len(probes):
            return 'operational', 'Model providers responding'
        if ok:
            return 'degraded', '; '.join(p[1] for p in probes if p[0] != 'operational')
        return 'outage', '; '.join(p[1] for p in probes)

    def _check_billing(self) -> Check:
        key = os.getenv('STRIPE_SECRET_KEY')
        if not key:
            return 'degraded', 'Payments not configured'
        return _from_http(_http_status('https://api.stripe.com/v1/balance', auth=(key, '')), 'Stripe')

    def _check_email(self) -> Check:
        provider = (os.getenv('EMAIL_PROVIDER') or ('brevo' if os.getenv('BREVO_API_KEY') else 'smtp')).lower()
        if provider == 'brevo' and os.getenv('BREVO_API_KEY'):
            return _from_http(_http_status('https://api.brevo.com/v3/account',
                                           headers={'api-key': os.getenv('BREVO_API_KEY')}), 'Email provider')
        if provider == 'sendgrid' and os.getenv('SENDGRID_API_KEY'):
            return _from_http(_http_status('https://api.sendgrid.com/v3/scopes',
                                           headers={'Authorization': f'Bearer {os.getenv("SENDGRID_API_KEY")}'}),
                              'Email provider')
        if os.getenv('SMTP_HOST') or os.getenv('SMTP_USER'):
            host = os.getenv('SMTP_HOST') or 'smtp-relay.brevo.com'
            port = int(os.getenv('SMTP_PORT') or 587)
            try:
                with smtplib.SMTP(host, port, timeout=_TIMEOUT) as smtp:
                    smtp.noop()
                return 'operational', 'Mail server reachable'
            except Exception as e:
                logger.info(f'SMTP status probe failed: {type(e).__name__}')
                return 'outage', 'Mail server unreachable'
        return 'degraded', 'No email provider configured'

    # ------------------------------------------------------------------
    # Legacy subscribers: only unsubscribe remains
    # ------------------------------------------------------------------

    def unsubscribe(self, token: str):
        """Remove a subscriber by token. Returns (ok, email)."""
        if not self._app:
            return False, None
        with self._app.app_context():
            from models import db, StatusSubscriber
            sub = StatusSubscriber.query.filter_by(token=token).first()
            if not sub:
                return False, None
            email = sub.email
            db.session.delete(sub)
            db.session.commit()
            return True, email


status_service = StatusService()
