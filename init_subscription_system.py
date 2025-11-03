"""
Initialize subscription system with default tiers and migrate existing users.
Run this script once to set up the credits-based monetization system.
"""
from app import app, db
from models import SubscriptionTier, UserSubscription, User
from datetime import datetime
from dateutil.relativedelta import relativedelta


def create_subscription_tiers():
    """Create default subscription tiers."""
    print("Creating subscription tiers...")

    tiers = [
        {
            'name': 'free',
            'display_name': 'Free Tier',
            'monthly_price': 0.0,
            'monthly_credits': 20,
            'description': 'Perfect for trying out the DevOps Agent',
            'features': [
                '20 agent actions per month',
                'Access to all cloud providers',
                'Basic support',
                'Community access'
            ]
        },
        {
            'name': 'starter',
            'display_name': 'Starter',
            'monthly_price': 19.0,
            'monthly_credits': 200,
            'description': 'For individual developers and small teams',
            'features': [
                '200 agent actions per month',
                'All cloud providers',
                'Priority email support',
                'Usage analytics',
                'API access'
            ]
        },
        {
            'name': 'professional',
            'display_name': 'Professional',
            'monthly_price': 79.0,
            'monthly_credits': 1000,
            'description': 'For growing teams and active DevOps workflows',
            'features': [
                '1,000 agent actions per month',
                'All cloud providers',
                'Priority support',
                'Advanced analytics',
                'API access',
                'Team collaboration',
                'Custom templates'
            ]
        },
        {
            'name': 'business',
            'display_name': 'Business',
            'monthly_price': 199.0,
            'monthly_credits': 3000,
            'description': 'For enterprises with high-volume automation needs',
            'features': [
                '3,000 agent actions per month',
                'All cloud providers',
                '24/7 priority support',
                'Advanced analytics & reporting',
                'API access',
                'Team collaboration',
                'Custom templates',
                'Dedicated account manager',
                'SLA guarantee',
                'Compliance reports'
            ]
        }
    ]

    created_count = 0
    for tier_data in tiers:
        # Check if tier already exists
        existing = SubscriptionTier.query.filter_by(name=tier_data['name']).first()

        if existing:
            print(f"  Tier '{tier_data['display_name']}' already exists, updating...")
            # Update existing tier
            existing.display_name = tier_data['display_name']
            existing.monthly_price = tier_data['monthly_price']
            existing.monthly_credits = tier_data['monthly_credits']
            existing.description = tier_data['description']
            existing.features = tier_data['features']
            existing.is_active = True
        else:
            print(f"  Creating tier '{tier_data['display_name']}'...")
            tier = SubscriptionTier(**tier_data)
            db.session.add(tier)
            created_count += 1

    db.session.commit()
    print(f"Subscription tiers set up successfully! ({created_count} new, {len(tiers) - created_count} updated)")


def migrate_existing_users():
    """Migrate existing users to free tier with initial credits."""
    print("\nMigrating existing users to subscription system...")

    # Get free tier
    free_tier = SubscriptionTier.query.filter_by(name='free').first()
    if not free_tier:
        print("ERROR: Free tier not found. Please run create_subscription_tiers() first.")
        return

    # Get all users without subscriptions
    users = User.query.all()
    migrated_count = 0

    for user in users:
        # Check if user already has subscription
        existing_subscription = UserSubscription.query.filter_by(user_id=user.id).first()

        if existing_subscription:
            print(f"  User {user.username} already has a subscription, skipping...")
            continue

        # Create free tier subscription
        subscription = UserSubscription(
            user_id=user.id,
            tier_id=free_tier.id,
            credits_remaining=free_tier.monthly_credits,
            current_period_start=datetime.utcnow(),
            current_period_end=datetime.utcnow() + relativedelta(months=1),
            payment_status='active'
        )

        db.session.add(subscription)
        migrated_count += 1
        print(f"  Migrated user '{user.username}' to Free tier with {free_tier.monthly_credits} credits")

    db.session.commit()
    print(f"Migration complete! {migrated_count} users migrated to free tier.")


def display_summary():
    """Display summary of subscription system."""
    print("\n" + "=" * 60)
    print("SUBSCRIPTION SYSTEM SUMMARY")
    print("=" * 60)

    # Count tiers
    tiers = SubscriptionTier.query.filter_by(is_active=True).order_by(SubscriptionTier.monthly_price).all()
    print(f"\nActive Subscription Tiers: {len(tiers)}")
    print("-" * 60)

    for tier in tiers:
        print(f"\n{tier.display_name} (${tier.monthly_price}/month)")
        print(f"  Credits: {tier.monthly_credits} per month")
        print(f"  Subscribers: {tier.subscriptions.count()}")

    # Count total subscriptions
    total_subs = UserSubscription.query.count()
    total_users = User.query.count()

    print("\n" + "-" * 60)
    print(f"Total Users: {total_users}")
    print(f"Users with Subscriptions: {total_subs}")
    print(f"Users without Subscriptions: {total_users - total_subs}")

    # Calculate total credits allocated
    total_credits = db.session.query(
        db.func.sum(UserSubscription.credits_remaining)
    ).scalar() or 0

    total_used = db.session.query(
        db.func.sum(UserSubscription.total_credits_used)
    ).scalar() or 0

    print(f"\nTotal Active Credits: {total_credits}")
    print(f"Total Credits Used (All Time): {total_used}")

    print("=" * 60)


def main():
    """Main initialization function."""
    print("\n" + "=" * 60)
    print("DevOps Agent - Subscription System Initialization")
    print("=" * 60 + "\n")

    with app.app_context():
        # Create tables if they don't exist
        print("Ensuring database tables exist...")
        db.create_all()
        print("Database tables ready.\n")

        # Create/update subscription tiers
        create_subscription_tiers()

        # Migrate existing users
        migrate_existing_users()

        # Display summary
        display_summary()

    print("\nInitialization complete!")
    print("\nNext steps:")
    print("  1. Restart your Flask application")
    print("  2. Test the /api/subscription endpoint")
    print("  3. Configure Stripe for payments (optional)")
    print("  4. Update frontend to show credits and upgrade options")
    print("\n" + "=" * 60 + "\n")


if __name__ == '__main__':
    main()
