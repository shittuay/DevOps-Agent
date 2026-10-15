"""Budget alerts: compare real AWS billed spend against the user's thresholds.

Until 2026-10-14 nothing read `BudgetAlert` rows at all: Settings > Budgets saved
them and no code ever checked them. Spend comes from AWS Cost Explorer through the
user's own credentials. If billing can't be read, the alert is left unchecked
(never reported as under budget).
"""
import logging
from datetime import date, timedelta
from typing import Dict, Optional, Tuple

from src.utils.timeutils import utcnow

logger = logging.getLogger(__name__)

# Each alert is checked at most this often; Cost Explorer data updates a few times a day.
CHECK_EVERY = timedelta(hours=24)


class BudgetCheckError(Exception):
    """Billing could not be read, so the budget state is unknown."""


def period_window(period: str, today: date) -> Tuple[date, date, str]:
    """(start, end_exclusive, label) of the spend window for an alert period.

    Monthly is month to date, weekly is Monday to date, daily is yesterday (the
    last complete day; Cost Explorer lags by up to a day).
    """
    if period == 'daily':
        start = today - timedelta(days=1)
        return start, today, f'yesterday ({start.isoformat()})'
    if period == 'weekly':
        start = today - timedelta(days=today.weekday())
        return start, today + timedelta(days=1), f'this week (since {start.isoformat()})'
    start = today.replace(day=1)
    return start, today + timedelta(days=1), f'this month (since {start.isoformat()})'


def period_spend(user_id: int, period: str, today: Optional[date] = None) -> Tuple[float, str, date]:
    """Billed spend for the period from Cost Explorer. Raises BudgetCheckError."""
    from services.cost_explorer import _get_user_boto_client
    today = today or utcnow().date()
    start, end, label = period_window(period, today)
    try:
        ce = _get_user_boto_client(user_id, 'ce', region='us-east-1')
        resp = ce.get_cost_and_usage(
            TimePeriod={'Start': start.isoformat(), 'End': end.isoformat()},
            Granularity='DAILY',
            Metrics=['UnblendedCost'],
        )
    except Exception as e:
        raise BudgetCheckError(str(e)) from e
    total = sum(float(p['Total']['UnblendedCost']['Amount']) for p in resp.get('ResultsByTime', []))
    return round(total, 2), label, start


def _notify(user_id: int, alert, spend: float, label: str) -> None:
    from services.notification_service import (Notification, NotificationPriority,
                                               _BASE_URL, _send_async)
    over = spend - alert.threshold_amount
    _send_async(user_id, 'cost', Notification(
        title=f'Budget exceeded: {alert.name}',
        message=(f'AWS spend {label} is ${spend:,.2f}, over your ${alert.threshold_amount:,.2f} '
                 f'{alert.period} budget by ${over:,.2f}.'),
        priority=NotificationPriority.HIGH,
        fields={'Spend': f'${spend:,.2f}', 'Budget': f'${alert.threshold_amount:,.2f}',
                'Period': alert.period},
        actions=[{'text': 'View costs', 'url': f'{_BASE_URL}/dashboard', 'primary': True}],
    ))
    try:
        from services.api_gateway import dispatch_webhook_event
        dispatch_webhook_event(user_id, 'cost.threshold', {
            'budget': {'id': alert.id, 'name': alert.name, 'period': alert.period,
                       'threshold': alert.threshold_amount},
            'spend': spend,
        })
    except Exception as e:
        logger.warning(f'Budget webhook skipped for user {user_id}: {e}')
    try:
        from models import User
        from services.email_service import EmailService
        user = User.query.get(user_id)
        if user and user.email:
            EmailService().send_email(
                user.email,
                f'Budget exceeded: {alert.name}',
                (f'<p>Your AWS spend {label} is <strong>${spend:,.2f}</strong>, over your '
                 f'${alert.threshold_amount:,.2f} {alert.period} budget "{_esc(alert.name)}".</p>'
                 f'<p><a href="{_BASE_URL}/dashboard">View costs</a> &middot; '
                 f'<a href="{_BASE_URL}/settings#budgets">Change budget alerts</a></p>'),
            )
    except Exception as e:
        logger.warning(f'Budget alert email failed for user {user_id}: {e}')


def _esc(text: str) -> str:
    from html import escape
    return escape(text or '')


def check_user_budgets(user_id: int, force: bool = False) -> Dict[str, int]:
    """Check the user's active budget alerts that are due. Returns counts."""
    from models import BudgetAlert, db
    now = utcnow()
    counts = {'checked': 0, 'triggered': 0, 'unreadable': 0}
    alerts = BudgetAlert.query.filter_by(user_id=user_id, is_active=True).all()
    for alert in alerts:
        if not force and alert.last_checked_at and now - _naive(alert.last_checked_at) < CHECK_EVERY:
            continue
        try:
            spend, label, start = period_spend(user_id, alert.period or 'monthly', now.date())
        except BudgetCheckError as e:
            counts['unreadable'] += 1
            logger.info(f'Budget {alert.id} not checked for user {user_id}: billing unreadable ({e})')
            continue
        counts['checked'] += 1
        alert.last_checked_amount = spend
        alert.last_checked_at = now
        already = alert.last_triggered and _naive(alert.last_triggered).date() >= start
        if spend >= alert.threshold_amount and not already:
            alert.last_triggered = now
            counts['triggered'] += 1
            db.session.commit()
            _notify(user_id, alert, spend, label)
    db.session.commit()
    return counts


def _naive(dt):
    return dt.replace(tzinfo=None) if dt is not None and dt.tzinfo else dt
