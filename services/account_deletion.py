"""Self-serve account deletion (Apple App Store guideline 5.1.1(v), and good practice anyway).

Deletes the user and every row that belongs to them. The FK graph has ~65 references to
users.id and no ON DELETE rules, so the ORM's ``db.session.delete(user)`` fails on Postgres
as soon as one child row exists. Instead this walks the schema at runtime:

- A column that names the owner (``user_id``, ``owner_id``, ``requester_id``, ``created_by``)
  deletes the row, and the rows that depend on it, recursively.
- Any other reference (``approver_id``, ``invited_by``, ``resolved_by``...) records what this
  user did to someone else's row; it is set to NULL so the other user's data survives.
- Below the first level, a nullable reference is set to NULL and a required one deletes.

Walking the live schema means a new table that references users is covered without edits.
"""
import logging
from typing import Optional

from sqlalchemy import delete, select, update

logger = logging.getLogger(__name__)

OWNER_COLUMNS = frozenset({'user_id', 'owner_id', 'requester_id', 'created_by'})
MAX_DEPTH = 8


class AccountDeletionBlocked(Exception):
    """The account can't be deleted yet; the message says what to do first."""


def _children(metadata, table):
    for child in metadata.sorted_tables:
        for fk in child.foreign_keys:
            if fk.column.table is table:
                yield child, fk.parent, fk.column


def _delete_where(session, metadata, table, condition, depth=0):
    if depth > MAX_DEPTH:
        raise RuntimeError(f'account deletion recursed too deep at {table.name}')
    for child, col, ref in _children(metadata, table):
        if child is table:
            continue
        keys = select(ref).where(condition)
        owned = depth == 0 and col.name in OWNER_COLUMNS
        if not owned and col.nullable:
            session.execute(update(child).where(col.in_(keys)).values({col.name: None}))
        else:
            _delete_where(session, metadata, child, col.in_(keys), depth + 1)
    session.execute(delete(table).where(condition))


def blocking_reason(user, by_admin: bool = False) -> Optional[str]:
    """Why this account can't be deleted right now, or None.

    ``by_admin``: a platform admin is deleting someone else (Admin › Users), so the
    "admins can't delete themselves" rule doesn't apply.
    """
    from models import Organization, OrganizationMember

    if not by_admin and (user.role or '') == 'admin':
        return ('Platform admin accounts can\'t be deleted here. Ask another admin to change '
                'your role first.')
    for org in Organization.query.filter_by(owner_id=user.id).all():
        others = OrganizationMember.query.filter(
            OrganizationMember.organization_id == org.id,
            OrganizationMember.user_id != user.id,
        ).count()
        if others:
            return (f'You own the team "{org.name}", which has other members. Make someone '
                    'else the owner or remove the members first.')
    return None


def _cancel_stripe_subscription(user_id: int) -> None:
    from models import UserSubscription

    sub = UserSubscription.query.filter_by(user_id=user_id).first()
    sub_id = getattr(sub, 'stripe_subscription_id', None) if sub else None
    if not sub_id:
        return
    from stripe_integration import StripePaymentService
    result = StripePaymentService.cancel_subscription(sub_id)
    if not result.get('success'):
        logger.error('Account deletion: Stripe cancel failed for user %s', user_id)
        raise AccountDeletionBlocked(
            'We could not cancel your paid plan, so your account was not deleted. '
            'Please try again, or contact support@devopsagent.io.')


def delete_account(user_id: int, by_admin: bool = False) -> None:
    """Cancel billing, then delete the user and everything they own, in one transaction."""
    from models import User, db

    user = db.session.get(User, user_id)
    if user is None:
        return
    reason = blocking_reason(user, by_admin=by_admin)
    if reason:
        raise AccountDeletionBlocked(reason)
    _cancel_stripe_subscription(user_id)

    users = User.__table__
    db.session.expunge_all()  # ORM copies of these rows must not be flushed or reloaded later
    try:
        _delete_where(db.session, db.metadata, users, users.c.id == user_id)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Account deletion failed for user %s', user_id)
        raise
    logger.warning('Account deleted by its owner: user %s', user_id)
