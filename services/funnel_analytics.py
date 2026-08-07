"""Signup-to-paid funnel, derived from data the app already stores.

The point of this module is to make one question answerable without guessing:
where do people stop? With a low signup count you cannot learn that from
aggregate totals -- "15 users, 40 conversations" hides whether one person sent
40 messages or forty people sent one each. Counting *distinct users per
milestone* separates a traffic problem from a product problem.

Every stage but one is reconstructed from existing tables, so history back to
the first signup is already there. The exception is checkout, which had no
storage at all before CheckoutAttempt -- nothing was written until money moved,
so an abandoned or erroring checkout left no trace.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func, distinct

from models import (
    db, User, ChatMessage, UserCloudCredential, CheckoutAttempt,
    CreditPurchase, UserSubscription, SubscriptionTier,
)

# Stage keys are stable identifiers; labels are for display.
STAGE_LABELS = {
    'signed_up': 'Signed up',
    'verified_email': 'Verified email',
    'sent_first_message': 'Sent a message',
    'returned': 'Came back (2+ days)',
    'connected_cloud': 'Connected a cloud account',
    'reached_checkout': 'Reached checkout',
    'paid': 'Paid',
}

STAGE_ORDER = [
    'signed_up',
    'verified_email',
    'sent_first_message',
    'returned',
    'connected_cloud',
    'reached_checkout',
    'paid',
]


def _cohort_user_ids(days: Optional[int]) -> Optional[List[int]]:
    """User ids in the cohort window, or None for 'all time'.

    Returning None rather than every id lets callers skip the IN clause
    entirely on the all-time view.
    """
    if not days:
        return None
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = db.session.query(User.id).filter(User.created_at >= cutoff).all()
    return [r[0] for r in rows]


def _scoped(query, column, cohort: Optional[List[int]]):
    if cohort is None:
        return query
    if not cohort:
        # Empty cohort must yield zero, not "unfiltered".
        return query.filter(False)
    return query.filter(column.in_(cohort))


def _count_distinct_users(model, cohort: Optional[List[int]], *filters) -> int:
    q = db.session.query(func.count(distinct(model.user_id)))
    for f in filters:
        q = q.filter(f)
    q = _scoped(q, model.user_id, cohort)
    return q.scalar() or 0


def _returned_user_ids(cohort: Optional[List[int]]) -> int:
    """Users with messages on two or more distinct calendar days.

    A second active day is a far better retention signal than a second
    conversation: starting two chats in one sitting is still one session.
    func.date() renders as date(...) on both SQLite (tests) and Postgres (prod).
    """
    day = func.date(ChatMessage.timestamp)
    q = (
        db.session.query(ChatMessage.user_id)
        .filter(ChatMessage.role == 'user')
        .group_by(ChatMessage.user_id)
        .having(func.count(distinct(day)) >= 2)
    )
    q = _scoped(q, ChatMessage.user_id, cohort)
    return q.count()


def _paid_user_ids(cohort: Optional[List[int]]) -> int:
    """Users who actually paid, by any route.

    Checked three ways because a payment can land through a completed checkout
    attempt, a credit purchase, or a subscription on a priced tier, and early
    manual/legacy grants do not always write all three.
    """
    ids = set()

    q = db.session.query(distinct(CheckoutAttempt.user_id)).filter(
        CheckoutAttempt.status == 'completed'
    )
    ids.update(r[0] for r in _scoped(q, CheckoutAttempt.user_id, cohort).all())

    q = db.session.query(distinct(CreditPurchase.user_id)).filter(
        CreditPurchase.payment_status == 'completed'
    )
    ids.update(r[0] for r in _scoped(q, CreditPurchase.user_id, cohort).all())

    q = (
        db.session.query(distinct(UserSubscription.user_id))
        .join(SubscriptionTier, UserSubscription.tier_id == SubscriptionTier.id)
        .filter(SubscriptionTier.monthly_price > 0)
        .filter(UserSubscription.payment_status == 'active')
    )
    ids.update(r[0] for r in _scoped(q, UserSubscription.user_id, cohort).all())

    return len(ids)


def get_funnel(days: Optional[int] = None) -> Dict[str, Any]:
    """Return distinct-user counts for each funnel stage.

    days=None means all time. Counts are per-milestone ("ever reached"), not
    strictly nested, so a later stage can in principle exceed an earlier one --
    that is a real signal (e.g. someone paid without ever connecting a cloud
    account), not a bug, and it is left visible rather than smoothed away.
    """
    cohort = _cohort_user_ids(days)

    signed_up = len(cohort) if cohort is not None else (db.session.query(func.count(User.id)).scalar() or 0)

    counts = {
        'signed_up': signed_up,
        'verified_email': _scoped(
            db.session.query(func.count(User.id)).filter(User.email_verified.is_(True)),
            User.id, cohort
        ).scalar() or 0,
        'sent_first_message': _count_distinct_users(
            ChatMessage, cohort, ChatMessage.role == 'user'
        ),
        'returned': _returned_user_ids(cohort),
        'connected_cloud': _count_distinct_users(
            UserCloudCredential, cohort, UserCloudCredential.is_active.is_(True)
        ),
        'reached_checkout': _count_distinct_users(CheckoutAttempt, cohort),
        'paid': _paid_user_ids(cohort),
    }

    stages = []
    prev = None
    for key in STAGE_ORDER:
        n = counts[key]
        stages.append({
            'key': key,
            'label': STAGE_LABELS[key],
            'count': n,
            # Share of signups -- the only denominator that stays meaningful
            # when a stage is skipped entirely.
            'pct_of_signups': round(100.0 * n / signed_up, 1) if signed_up else 0.0,
            # Drop-off against the previous stage, for spotting the cliff.
            'pct_of_previous': round(100.0 * n / prev, 1) if prev else None,
            'lost_from_previous': (prev - n) if prev is not None and prev >= n else None,
        })
        prev = n

    return {
        'window_days': days,
        'generated_at': datetime.utcnow().isoformat(),
        'signed_up': signed_up,
        'stages': stages,
        'biggest_drop': _biggest_drop(stages),
    }


def _biggest_drop(stages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The stage transition that loses the most users -- the thing to fix first."""
    worst = None
    for i in range(1, len(stages)):
        lost = stages[i].get('lost_from_previous')
        if lost is None:
            continue
        if worst is None or lost > worst['lost']:
            worst = {
                'from': stages[i - 1]['label'],
                'to': stages[i]['label'],
                'lost': lost,
                'pct_retained': stages[i].get('pct_of_previous'),
            }
    return worst


def get_checkout_attempts(limit: int = 25) -> List[Dict[str, Any]]:
    """Recent checkout attempts, newest first.

    Failed rows are the valuable ones: they are the users who tried to give you
    money and could not, which no other table records.
    """
    rows = (
        CheckoutAttempt.query
        .order_by(CheckoutAttempt.created_at.desc())
        .limit(limit)
        .all()
    )
    out = []
    for r in rows:
        d = r.to_dict()
        d['user_email'] = r.user.email if r.user else None
        out.append(d)
    return out


def get_checkout_summary() -> Dict[str, Any]:
    """Counts by checkout status, so a broken key shows up as a failure spike."""
    rows = (
        db.session.query(CheckoutAttempt.status, func.count(CheckoutAttempt.id))
        .group_by(CheckoutAttempt.status)
        .all()
    )
    summary = {status: count for status, count in rows}
    return {
        'created': summary.get('created', 0),
        'completed': summary.get('completed', 0),
        'failed': summary.get('failed', 0),
        'total': sum(summary.values()),
    }
