"""Verify the new pricing tiers."""
from app import app, db
from models import SubscriptionTier

with app.app_context():
    print("\n" + "=" * 80)
    print("ACTIVE PRICING TIERS")
    print("=" * 80)
    print()

    tiers = SubscriptionTier.query.filter_by(is_active=True).order_by(SubscriptionTier.monthly_price).all()

    for tier in tiers:
        print(f"Name: {tier.display_name}")
        print(f"  Price: ${tier.monthly_price}/month")
        print(f"  Credits: {tier.monthly_credits}")
        print(f"  Daily Limit: {tier.daily_action_limit if tier.daily_action_limit else 'Unlimited'}")
        print(f"  Max Duration: {tier.max_duration_days if tier.max_duration_days else 'No limit'} days")
        print(f"  Features: {len(tier.features)} features")
        print()

    print("=" * 80)
    print(f"Total active tiers: {len(tiers)}")
    print("=" * 80)
