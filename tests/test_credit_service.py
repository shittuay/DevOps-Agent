import pytest
from src.utils.timeutils import utcnow


@pytest.fixture
def user_with_sub(test_user, db_session):
    from models import db, SubscriptionTier, UserSubscription
    from datetime import datetime
    tier = SubscriptionTier.query.filter_by(name='free').first()
    if not tier:
        tier = SubscriptionTier(name='free', display_name='Free', monthly_credits=20)
        db.session.add(tier)
        db.session.commit()
    sub = UserSubscription(
        user_id=test_user.id,
        tier_id=tier.id,
        credits_remaining=10,
        current_period_start=utcnow(),
        current_period_end=utcnow(),
    )
    db.session.add(sub)
    db.session.commit()
    yield test_user, sub
    # Explicit teardown before test_user cleanup removes the user
    s = UserSubscription.query.get(sub.id)
    if s:
        db.session.delete(s)
        db.session.commit()


def test_balance_returns_credits(user_with_sub):
    from services.credit_service import CreditService
    user, sub = user_with_sub
    assert CreditService.balance(user.id) == 10


def test_balance_returns_zero_for_no_subscription(test_user):
    from services.credit_service import CreditService
    assert CreditService.balance(test_user.id) == 0


def test_deduct_reduces_by_one(user_with_sub):
    from services.credit_service import CreditService
    user, sub = user_with_sub
    remaining = CreditService.deduct(user.id)
    assert remaining == 9
    assert CreditService.balance(user.id) == 9


def test_deduct_floors_at_zero(user_with_sub, db_session):
    from services.credit_service import CreditService
    user, sub = user_with_sub
    sub.credits_remaining = 0
    db_session.commit()
    remaining = CreditService.deduct(user.id)
    assert remaining == 0
    assert CreditService.balance(user.id) == 0


def test_deduct_commit_false_does_not_persist_without_commit(user_with_sub, db_session):
    from services.credit_service import CreditService
    user, sub = user_with_sub
    CreditService.deduct(user.id, commit=False)
    db_session.rollback()
    assert CreditService.balance(user.id) == 10


def test_grant_increases_balance(user_with_sub):
    from services.credit_service import CreditService
    user, sub = user_with_sub
    new_bal = CreditService.grant(user.id, 5)
    assert new_bal == 15
    assert CreditService.balance(user.id) == 15


def test_grant_returns_zero_for_no_subscription(test_user):
    from services.credit_service import CreditService
    result = CreditService.grant(test_user.id, 5)
    assert result == 0
