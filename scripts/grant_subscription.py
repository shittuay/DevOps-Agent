"""
Manually grant a subscription to a user who paid but didn't receive it.
This handles cases where the Stripe webhook didn't fire or failed.

Usage:
    python scripts/grant_subscription.py yabiolashittu@gmail.com starter
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import User, UserSubscription, SubscriptionTier
from datetime import datetime
from src.utils.timeutils import utcnow

def grant_subscription(email, tier_name):
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        if not user:
            print(f"ERROR: User not found for email: {email}")
            sys.exit(1)

        tier = SubscriptionTier.query.filter_by(name=tier_name).first()
        if not tier:
            print(f"ERROR: Tier '{tier_name}' not found. Available tiers:")
            for t in SubscriptionTier.query.all():
                print(f"  - {t.name} ({t.display_name}): {t.monthly_credits} credits/month")
            sys.exit(1)

        subscription = UserSubscription.query.filter_by(user_id=user.id).first()
        if subscription:
            old_tier = subscription.tier.name if subscription.tier else 'none'
            old_credits = subscription.credits_remaining
            subscription.tier_id = tier.id
            subscription.payment_status = 'active'
            subscription.payment_gateway = 'stripe'
            subscription.credits_remaining = tier.monthly_credits
            subscription.credits_used_this_month = 0
            from dateutil.relativedelta import relativedelta
            subscription.current_period_start = utcnow()
            subscription.current_period_end = utcnow() + relativedelta(months=1)
            db.session.commit()
            print(f"UPDATED subscription for {email}:")
            print(f"  Tier: {old_tier} -> {tier_name}")
            print(f"  Credits: {old_credits} -> {tier.monthly_credits}")
        else:
            from dateutil.relativedelta import relativedelta
            subscription = UserSubscription(
                user_id=user.id,
                tier_id=tier.id,
                credits_remaining=tier.monthly_credits,
                payment_status='active',
                payment_gateway='stripe',
                current_period_start=utcnow(),
                current_period_end=utcnow() + relativedelta(months=1),
            )
            db.session.add(subscription)
            db.session.commit()
            print(f"CREATED subscription for {email}:")
            print(f"  Tier: {tier_name}")
            print(f"  Credits: {tier.monthly_credits}")

        print(f"\nUser {email} (id={user.id}) now has {tier_name} tier with {subscription.credits_remaining} credits.")

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python scripts/grant_subscription.py <email> <tier_name>")
        print("Example: python scripts/grant_subscription.py user@example.com starter")
        sys.exit(1)
    grant_subscription(sys.argv[1], sys.argv[2])
