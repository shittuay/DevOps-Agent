"""Free plan: 20 credits a month, refilled like every other plan (owner decision, 2026-10-14).

Chat and /api/v1 treated free credits as a one-time trial and never refilled them,
while Billing refilled them monthly and the landing page said "per month".
"""
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _free_sub(user, credits=0, ended_days_ago=1):
    from models import SubscriptionTier, UserSubscription, db
    from src.utils.timeutils import utcnow
    tier = SubscriptionTier.query.filter_by(name='free').first()
    if tier is None:
        tier = SubscriptionTier(name='free', display_name='Free', monthly_credits=20,
                                monthly_price=0.0, is_active=True)
        db.session.add(tier)
        db.session.commit()
    sub = UserSubscription.query.filter_by(user_id=user.id).first()
    if sub is None:
        sub = UserSubscription(user_id=user.id, tier_id=tier.id)
        db.session.add(sub)
    sub.tier_id = tier.id
    sub.credits_remaining = credits
    sub.total_credits_used = 20
    sub.current_period_end = utcnow() - timedelta(days=ended_days_ago)
    db.session.commit()
    return sub


def test_free_credits_refill_after_the_period(app, db_session, test_user):
    sub = _free_sub(test_user)
    assert sub.refresh_credits_if_due() is True
    assert sub.credits_remaining == 20
    assert sub.refresh_credits_if_due() is False, 'not again until next period'


def test_free_credits_do_not_refill_early(app, db_session, test_user):
    sub = _free_sub(test_user, credits=3, ended_days_ago=-10)
    assert sub.refresh_credits_if_due() is False
    assert sub.credits_remaining == 3


def test_no_path_skips_the_free_refill():
    for rel in ('app.py', 'api/v1/conversations.py'):
        src = (ROOT / rel).read_text()
        assert "tier_name != 'free' and subscription.should_reset_credits()" not in src, rel
        assert 'one-time trial' not in src, rel


def test_out_of_credits_message_says_when_they_refill():
    from datetime import datetime
    from services.chat_service import generate_upgrade_pitch
    text = generate_upgrade_pitch(datetime(2026, 11, 3))
    assert 'November 3' in text and 'refill' in text
    assert 'trial has ended' not in text.lower()
    assert '200 AI messages per month' in text  # Starter's real allowance, not a hardcoded 500
