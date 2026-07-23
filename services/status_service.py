"""
Status Page Service

Manages public service health checks and Brevo status email notifications.
Subscribers receive emails when incidents fire or resolve.
"""
import os
import secrets
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Service definitions for health checks
_SERVICES = [
    {'key': 'api',     'name': 'API',            'description': 'Core REST API and chat endpoints'},
    {'key': 'auth',    'name': 'Authentication', 'description': 'Login, 2FA, session management'},
    {'key': 'db',      'name': 'Database',       'description': 'Data storage and queries'},
    {'key': 'ai',      'name': 'AI / Chat',      'description': 'Kimi K3 and Claude inference'},
    {'key': 'billing', 'name': 'Billing',        'description': 'Stripe payments and subscriptions'},
    {'key': 'email',   'name': 'Email',          'description': 'Brevo transactional email delivery'},
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


class StatusService:
    def __init__(self):
        self._app = None
        self._email_service = None

    def set_app(self, app):
        self._app = app

    def set_email_service(self, email_service):
        self._email_service = email_service

    # ------------------------------------------------------------------
    # Health checks
    # ------------------------------------------------------------------

    def check_health(self):
        """Run health checks for all services. Returns list of service status dicts."""
        results = []
        for svc in _SERVICES:
            checker = getattr(self, f'_check_{svc["key"]}', None)
            if checker:
                status, detail = checker()
            else:
                status, detail = 'unknown', 'No health check configured'
            results.append({
                'key':         svc['key'],
                'name':        svc['name'],
                'description': svc['description'],
                'status':      status,
                'detail':      detail,
                'color':       _STATUS_COLORS.get(status, _STATUS_COLORS['unknown']),
                'label':       _STATUS_LABELS.get(status, 'Unknown'),
            })
        return results

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

    def _check_api(self):
        if not self._app:
            return 'unknown', 'App not initialised'
        return 'operational', 'API responding normally'

    def _check_auth(self):
        if not self._app:
            return 'unknown', 'App not initialised'
        try:
            with self._app.app_context():
                from models import User
                User.query.limit(1).all()
            return 'operational', 'Auth service active'
        except Exception as e:
            logger.warning(f'Auth health check failed: {e}')
            return 'degraded', 'Auth query issue'

    def _check_db(self):
        if not self._app:
            return 'unknown', 'App not initialised'
        try:
            with self._app.app_context():
                from models import db
                db.session.execute(db.text('SELECT 1'))
            return 'operational', 'Database reachable'
        except Exception as e:
            logger.warning(f'DB health check failed: {e}')
            return 'outage', f'Database unreachable: {str(e)[:60]}'

    def _check_ai(self):
        has_anthropic = bool(os.getenv('ANTHROPIC_API_KEY'))
        has_kimi = bool(os.getenv('MOONSHOT_API_KEY'))
        if has_anthropic or has_kimi:
            return 'operational', 'AI inference available'
        return 'degraded', 'No AI API key configured'

    def _check_billing(self):
        has_stripe = bool(os.getenv('STRIPE_SECRET_KEY'))
        if not has_stripe:
            return 'degraded', 'Stripe not configured'
        return 'operational', 'Payment processing active'

    def _check_email(self):
        has_brevo = bool(os.getenv('BREVO_API_KEY'))
        has_smtp = bool(os.getenv('SMTP_USER') and os.getenv('SMTP_PASS'))
        if has_brevo:
            return 'operational', 'Brevo email delivery active'
        if has_smtp:
            return 'operational', 'SMTP email delivery active'
        return 'degraded', 'No email provider configured'

    # ------------------------------------------------------------------
    # Subscriber management
    # ------------------------------------------------------------------

    def subscribe(self, email: str):
        """
        Create or re-confirm a subscriber. Returns (ok: bool, message: str).
        Sends a Brevo confirmation email.
        """
        if not self._app:
            return False, 'Service not initialised'
        with self._app.app_context():
            from models import db, StatusSubscriber
            existing = StatusSubscriber.query.filter_by(email=email).first()
            if existing and existing.confirmed:
                return False, 'already_subscribed'
            if existing:
                token = existing.token
            else:
                token = secrets.token_urlsafe(32)
                sub = StatusSubscriber(email=email, token=token)
                db.session.add(sub)
                db.session.commit()

            self._send_confirmation_email(email, token)
            return True, 'confirmation_sent'

    def confirm(self, token: str):
        """Confirm a subscriber by token. Returns (ok, email)."""
        if not self._app:
            return False, None
        with self._app.app_context():
            from models import db, StatusSubscriber
            sub = StatusSubscriber.query.filter_by(token=token).first()
            if not sub:
                return False, None
            if not sub.confirmed:
                sub.confirmed = True
                sub.confirmed_at = datetime.utcnow()
                db.session.commit()
            return True, sub.email

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

    def _get_confirmed_emails(self):
        if not self._app:
            return []
        with self._app.app_context():
            from models import StatusSubscriber
            return [s.email for s in StatusSubscriber.query.filter_by(confirmed=True).all()]

    # ------------------------------------------------------------------
    # Brevo email dispatch
    # ------------------------------------------------------------------

    def _base_url(self):
        return os.getenv('BASE_URL', 'https://devopsagent.io')

    def _send_confirmation_email(self, email: str, token: str):
        if not self._email_service:
            return
        confirm_url = f'{self._base_url()}/status/confirm/{token}'
        unsub_url = f'{self._base_url()}/status/unsubscribe/{token}'
        html = self._email_service._wrap_html(f"""
            <h2 style="color:#333;margin-bottom:12px;">Confirm Status Notifications</h2>
            <p>You requested status update notifications for DevOps Agent.</p>
            <p>Click the button below to confirm your subscription and start receiving alerts when services are impacted.</p>
            <div style="text-align:center;margin:28px 0;">
                <a href="{confirm_url}"
                   style="display:inline-block;padding:12px 32px;background:linear-gradient(135deg,#FF4D1C,#f7931e);color:white;text-decoration:none;border-radius:8px;font-weight:600;">
                    Confirm Subscription
                </a>
            </div>
            <p style="font-size:12px;color:#999;text-align:center;">
                Don't want these emails?
                <a href="{unsub_url}" style="color:#999;">Unsubscribe</a>
            </p>
        """)
        self._email_service.send_email(email, 'Confirm Your Status Notifications — DevOps Agent', html)

    def broadcast_incident(self, event_type: str, alert_data: dict):
        """
        Broadcast a status email to all confirmed subscribers.
        event_type: 'firing' | 'resolved'
        """
        if not self._email_service:
            return
        subscribers = self._get_confirmed_emails()
        if not subscribers:
            return

        rule_name = alert_data.get('rule_name', 'Service Alert')
        message = alert_data.get('message', '')
        severity = alert_data.get('severity', 'medium').upper()
        ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
        status_url = f'{self._base_url()}/status'

        if event_type == 'firing':
            subject = f'[DevOps Agent] Incident: {rule_name}'
            badge_color = '#ef4444'
            badge_text = 'INCIDENT'
            heading = 'Service Alert Triggered'
            intro = 'An issue has been detected that may affect your experience.'
        else:
            subject = f'[DevOps Agent] Resolved: {rule_name}'
            badge_color = '#22c55e'
            badge_text = 'RESOLVED'
            heading = 'Issue Resolved'
            intro = 'The issue has been resolved. All services are operating normally.'

        for email in subscribers:
            # per-subscriber unsubscribe link requires their token
            unsub_url = self._get_unsub_url(email)
            html = self._email_service._wrap_html(f"""
                <div style="text-align:center;margin-bottom:20px;">
                    <span style="display:inline-block;padding:4px 14px;background:{badge_color};color:white;
                                 border-radius:20px;font-size:12px;font-weight:700;letter-spacing:1px;">
                        {badge_text}
                    </span>
                </div>
                <h2 style="color:#333;margin-bottom:8px;">{heading}</h2>
                <p>{intro}</p>
                <table style="width:100%;border-collapse:collapse;margin:20px 0;font-size:14px;">
                    <tr style="background:#f9f9f9;">
                        <td style="padding:8px 12px;font-weight:600;color:#555;width:35%;">Alert</td>
                        <td style="padding:8px 12px;color:#333;">{rule_name}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px 12px;font-weight:600;color:#555;">Severity</td>
                        <td style="padding:8px 12px;color:#333;">{severity}</td>
                    </tr>
                    <tr style="background:#f9f9f9;">
                        <td style="padding:8px 12px;font-weight:600;color:#555;">Time</td>
                        <td style="padding:8px 12px;color:#333;">{ts}</td>
                    </tr>
                    {'<tr><td style="padding:8px 12px;font-weight:600;color:#555;">Details</td><td style="padding:8px 12px;color:#333;">' + message + '</td></tr>' if message else ''}
                </table>
                <div style="text-align:center;margin:24px 0;">
                    <a href="{status_url}"
                       style="display:inline-block;padding:12px 32px;background:linear-gradient(135deg,#FF4D1C,#f7931e);color:white;text-decoration:none;border-radius:8px;font-weight:600;">
                        View Status Page
                    </a>
                </div>
                <p style="font-size:12px;color:#999;text-align:center;">
                    <a href="{unsub_url}" style="color:#999;">Unsubscribe from status notifications</a>
                </p>
            """)
            self._email_service.send_email(email, subject, html)

        logger.info(f'Status broadcast sent to {len(subscribers)} subscriber(s): {event_type} — {rule_name}')

    def _get_unsub_url(self, email: str) -> str:
        if not self._app:
            return f'{self._base_url()}/status'
        with self._app.app_context():
            from models import StatusSubscriber
            sub = StatusSubscriber.query.filter_by(email=email).first()
            if sub:
                return f'{self._base_url()}/status/unsubscribe/{sub.token}'
        return f'{self._base_url()}/status'


status_service = StatusService()
