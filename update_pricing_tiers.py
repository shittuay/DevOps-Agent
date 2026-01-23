"""
Update subscription tiers to sustainable pricing model.
This replaces the money-losing free tier with a trial + demo model.
"""
from app import app, db
from models import SubscriptionTier, UserSubscription, User
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta


def create_new_pricing_tiers():
    """Create updated, sustainable subscription tiers."""
    print("=" * 70)
    print("UPDATING TO SUSTAINABLE PRICING MODEL")
    print("=" * 70)
    print()

    tiers = [
        {
            'name': 'trial',
            'display_name': '7-Day Trial',
            'monthly_price': 0.0,
            'monthly_credits': 10,  # Reduced from 20 to 10
            'description': 'Try DevOps Agent risk-free for 7 days',
            'features': [
                '10 AI agent actions total',
                '3 actions per day limit',
                'Full access to all features',
                'All cloud providers',
                'Community support',
                'Valid for 7 days only'
            ],
            'max_duration_days': 7,
            'daily_action_limit': 3
        },
        {
            'name': 'starter',
            'display_name': 'Starter',
            'monthly_price': 29.0,  # Increased from $19 to $29
            'monthly_credits': 100,  # Reduced from 200 to 100
            'description': 'Perfect for individual developers and freelancers',
            'features': [
                '100 AI agent actions per month',
                '10 actions per day limit',
                'All cloud providers (AWS, GCP, Azure)',
                'Infrastructure monitoring',
                'Cost optimization recommendations',
                'Security scanning',
                'Email support',
                'Team collaboration (up to 3 users)'
            ],
            'daily_action_limit': 10
        },
        {
            'name': 'professional',
            'display_name': 'Professional',
            'monthly_price': 99.0,  # Increased from $79 to $99
            'monthly_credits': 500,  # Reduced from 1,000 to 500
            'description': 'For growing teams with active DevOps workflows',
            'features': [
                '500 AI agent actions per month',
                '30 actions per day limit',
                'All cloud providers',
                'Infrastructure monitoring & alerts',
                'Advanced cost optimization',
                'Security compliance scanning',
                'Priority email & chat support',
                'Team collaboration (up to 10 users)',
                'API access',
                'Custom dashboards',
                'Usage analytics'
            ],
            'daily_action_limit': 30
        },
        {
            'name': 'business',
            'display_name': 'Business',
            'monthly_price': 249.0,  # Increased from $199 to $249
            'monthly_credits': 1500,  # Reduced from 3,000 to 1,500
            'description': 'For enterprises with high-volume automation needs',
            'features': [
                '1,500 AI agent actions per month',
                '100 actions per day limit',
                'All cloud providers',
                'Real-time infrastructure monitoring',
                'Advanced cost optimization & forecasting',
                'Compliance & security reports',
                '24/7 priority support',
                'Unlimited team collaboration',
                'API access with higher rate limits',
                'Custom integrations',
                'SLA guarantee (99.9% uptime)',
                'Dedicated account manager',
                'Quarterly business reviews'
            ],
            'daily_action_limit': 100
        },
        {
            'name': 'enterprise',
            'display_name': 'Enterprise',
            'monthly_price': 599.0,
            'monthly_credits': 4000,
            'description': 'Custom solutions for large organizations',
            'features': [
                '4,000 AI agent actions per month',
                'Unlimited daily usage',
                'All cloud providers',
                'White-glove onboarding',
                'Custom infrastructure automation',
                'Advanced security & compliance',
                '24/7 phone & priority support',
                'Unlimited team collaboration',
                'Dedicated API access',
                'Custom integrations & workflows',
                'SLA guarantee (99.95% uptime)',
                'Dedicated CSM & Technical Account Manager',
                'Monthly strategy sessions',
                'On-premise deployment option',
                'Training & certification'
            ],
            'daily_action_limit': None  # Unlimited
        }
    ]

    created_count = 0
    updated_count = 0

    for tier_data in tiers:
        existing = SubscriptionTier.query.filter_by(name=tier_data['name']).first()

        if existing:
            print(f"Updating: {tier_data['display_name']} - ${tier_data['monthly_price']}/month")
            existing.display_name = tier_data['display_name']
            existing.monthly_price = tier_data['monthly_price']
            existing.monthly_credits = tier_data['monthly_credits']
            existing.description = tier_data['description']
            existing.features = tier_data['features']
            existing.is_active = True
            existing.max_duration_days = tier_data.get('max_duration_days')
            existing.daily_action_limit = tier_data.get('daily_action_limit')
            updated_count += 1
        else:
            print(f"Creating: {tier_data['display_name']} - ${tier_data['monthly_price']}/month")
            tier = SubscriptionTier(**tier_data)
            db.session.add(tier)
            created_count += 1

    # Deactivate old "free" tier if it exists
    old_free = SubscriptionTier.query.filter_by(name='free').first()
    if old_free:
        print(f"\nDeactivating old 'Free' tier...")
        old_free.is_active = False
        updated_count += 1

    db.session.commit()
    print(f"\n[OK] Success: {created_count} new tiers created, {updated_count} tiers updated")
    return created_count, updated_count


def migrate_free_users_to_trial():
    """Convert existing free tier users to trial."""
    print("\n" + "=" * 70)
    print("MIGRATING FREE TIER USERS TO TRIAL")
    print("=" * 70)
    print()

    free_tier = SubscriptionTier.query.filter_by(name='free').first()
    trial_tier = SubscriptionTier.query.filter_by(name='trial').first()

    if not trial_tier:
        print("ERROR: Trial tier not found!")
        return 0

    if not free_tier:
        print("No free tier found, skipping migration...")
        return 0

    # Find all users on free tier
    free_subs = UserSubscription.query.filter_by(tier_id=free_tier.id).all()

    migrated_count = 0
    for sub in free_subs:
        user = User.query.get(sub.user_id)
        print(f"Migrating user: {user.username}")

        # Update to trial tier
        sub.tier_id = trial_tier.id
        sub.credits_remaining = trial_tier.monthly_credits
        sub.current_period_start = datetime.utcnow()
        sub.current_period_end = datetime.utcnow() + timedelta(days=7)  # 7-day trial
        sub.payment_status = 'trial'

        migrated_count += 1

    db.session.commit()
    print(f"\n[OK] Migrated {migrated_count} users from Free to Trial")

    # Send email notification (placeholder)
    print(f"\nIMPORTANT: Send email to {migrated_count} users:")
    print("  - Explain pricing changes")
    print("  - Offer 30% discount for first month")
    print("  - Highlight value proposition")

    return migrated_count


def display_pricing_summary():
    """Display updated pricing summary with economics."""
    print("\n" + "=" * 70)
    print("NEW PRICING STRUCTURE & ECONOMICS")
    print("=" * 70)
    print()

    tiers = SubscriptionTier.query.filter_by(is_active=True).order_by(SubscriptionTier.monthly_price).all()

    # Cost per action estimate
    cost_per_action = 0.05  # $0.05 per AI action (Claude API)

    print(f"{'Tier':<15} {'Price':<10} {'Credits':<10} {'API Cost':<12} {'Profit':<12} {'Margin':<10}")
    print("-" * 70)

    total_revenue = 0
    total_cost = 0

    for tier in tiers:
        price = tier.monthly_price
        credits = tier.monthly_credits
        api_cost = credits * cost_per_action
        profit = price - api_cost
        margin = (profit / price * 100) if price > 0 else 0

        print(f"{tier.display_name:<15} ${price:<9.2f} {credits:<10} ${api_cost:<11.2f} ${profit:<11.2f} {margin:>6.1f}%")

        # Calculate total if we had 100 users per tier (example)
        total_revenue += price
        total_cost += api_cost

    print("-" * 70)
    print(f"{'TOTAL':<15} ${total_revenue:<9.2f} {'':<10} ${total_cost:<11.2f} ${total_revenue - total_cost:<11.2f}")

    print("\nKey Improvements:")
    print("  • Eliminated money-losing free tier (-$1/user)")
    print("  • Trial tier: Minimal loss for 7 days only")
    print("  • All paid tiers: 65-85% profit margins")
    print("  • Daily limits prevent abuse")
    print("  • Sustainable from day 1")

    print("\nProjected Revenue (1,000 users):")
    print("  • 600 Trial (short-term): $0 revenue, -$300 cost")
    print("  • 250 Starter: $7,250 revenue, -$1,250 cost = +$6,000 profit")
    print("  • 100 Professional: $9,900 revenue, -$2,500 cost = +$7,400 profit")
    print("  • 40 Business: $9,960 revenue, -$3,000 cost = +$6,960 profit")
    print("  • 10 Enterprise: $5,990 revenue, -$2,000 cost = +$3,990 profit")
    print("  " + "-" * 60)
    print("  TOTAL: $33,100 revenue - $9,050 costs = $24,050/month profit")
    print("  Margin: 73%")

    print("\n" + "=" * 70)


def add_demo_mode_flag():
    """Add demo_mode flag to users for free exploration."""
    print("\n" + "=" * 70)
    print("ADDING DEMO MODE SUPPORT")
    print("=" * 70)
    print()

    print("Demo Mode Features:")
    print("  • View dashboard with sample data")
    print("  • Explore UI without API costs")
    print("  • Pre-written Q&A (no AI)")
    print("  • Mock infrastructure")
    print("  • Unlimited time")
    print("  • Zero cost to you!")

    print("\nDemo mode will be the default for:")
    print("  • New signups (before trial)")
    print("  • Expired trial users")
    print("  • Cancelled subscriptions")

    print("\n[OK] Demo mode concept ready for implementation")


def main():
    """Main execution function."""
    import sys

    print("\n" + "=" * 70)
    print("DevOps Agent - Pricing Update to Sustainable Model")
    print("=" * 70)
    print()

    # Check for --yes flag for non-interactive mode
    if '--yes' not in sys.argv:
        confirmation = input("This will update pricing for ALL tiers. Continue? (yes/no): ")
        if confirmation.lower() != 'yes':
            print("\nCancelled. No changes made.")
            return
    else:
        print("Running in non-interactive mode (--yes flag provided)")
        print("Proceeding with pricing update...")

    with app.app_context():
        # Ensure database tables exist
        print("\nVerifying database...")
        db.create_all()

        # Create new pricing tiers
        created, updated = create_new_pricing_tiers()

        # Migrate free tier users
        migrated = migrate_free_users_to_trial()

        # Show new pricing summary
        display_pricing_summary()

        # Demo mode info
        add_demo_mode_flag()

    print("\n" + "=" * 70)
    print("MIGRATION COMPLETE!")
    print("=" * 70)
    print()
    print("Next Steps:")
    print("  1. Restart Flask application")
    print("  2. Implement demo mode UI")
    print("  3. Add rate limiting (Redis)")
    print("  4. Update pricing page")
    print("  5. Send email to migrated users")
    print("  6. Monitor conversion rates")
    print()
    print("Expected Result:")
    print("  • Eliminate losses from free tier")
    print("  • 70%+ profit margins")
    print("  • Sustainable, scalable business")
    print()
    print("=" * 70 + "\n")


if __name__ == '__main__':
    main()
