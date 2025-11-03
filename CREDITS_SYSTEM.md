# Credits-Based Monetization System

## Overview

The DevOps Agent now includes a complete credits-based monetization system that allows you to:
- Charge users per agent action (1 credit = 1 agent interaction)
- Offer multiple subscription tiers with monthly credits
- Sell one-time credit packs
- Track usage and generate analytics
- Integrate with Stripe for payments (optional)

## Subscription Tiers

### Free Tier
- **Price:** $0/month
- **Credits:** 20 per month
- **Features:**
  - Access to all cloud providers
  - Basic support
  - Community access

### Starter
- **Price:** $19/month
- **Credits:** 200 per month
- **Features:**
  - All Free tier features
  - Priority email support
  - Usage analytics
  - API access

### Professional
- **Price:** $79/month
- **Credits:** 1,000 per month
- **Features:**
  - All Starter tier features
  - Advanced analytics
  - Team collaboration
  - Custom templates

### Business
- **Price:** $199/month
- **Credits:** 3,000 per month
- **Features:**
  - All Professional tier features
  - 24/7 priority support
  - Dedicated account manager
  - SLA guarantee
  - Compliance reports

## Credit Packs (One-time Purchases)

Users can purchase additional credits that never expire:

- **100 credits** - $10 ($0.10 per credit)
- **250 credits** - $20 ($0.08 per credit) ⭐ Popular
- **500 credits** - $35 ($0.07 per credit)
- **1,000 credits** - $60 ($0.06 per credit)

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

The new dependency is `stripe>=8.0.0` (optional, only needed if you want payment processing).

### 2. Initialize the Database

Run the initialization script to create subscription tiers and migrate existing users:

```bash
python init_subscription_system.py
```

This will:
- Create all necessary database tables
- Set up the 4 default subscription tiers
- Migrate all existing users to the Free tier with 20 credits
- Display a summary of the system

### 3. Start Your Application

```bash
python app.py
```

The application will run on `http://localhost:5000`

## How It Works

### Credit Deduction

Every time a user sends a message to the agent:
1. System checks if user has available credits
2. If yes, deducts 1 credit BEFORE processing
3. Processes the message with Claude AI
4. Logs the usage in the `usage_logs` table
5. Returns response with updated credit count

### Monthly Reset

Credits automatically reset at the start of each billing period:
- System checks `current_period_end` date
- When period expires, calls `reset_monthly_credits()`
- Sets `credits_remaining` to tier's `monthly_credits`
- Updates period dates for next month
- Resets `credits_used_this_month` to 0

### Out of Credits

When a user runs out of credits, the API returns:

```json
{
  "error": "insufficient_credits",
  "message": "You have run out of credits. Please upgrade your plan or purchase more credits.",
  "credits_remaining": 0,
  "tier": { ... }
}
```

HTTP Status Code: `402 Payment Required`

## API Endpoints

### Subscription Management

#### GET /api/subscription
Get current user's subscription details
```json
{
  "subscription": {
    "credits_remaining": 15,
    "credits_used_this_month": 5,
    "total_credits_used": 100,
    "tier": { ... },
    "current_period_end": "2025-12-01T00:00:00"
  },
  "available_tiers": [ ... ]
}
```

#### GET /api/subscription/tiers
Get all available subscription tiers (public)

#### POST /api/subscription/upgrade
Upgrade to a different tier
```json
{
  "tier_id": 2
}
```

### Credits Management

#### GET /api/credits/packs
Get available credit pack options

#### POST /api/credits/purchase
Purchase a credit pack
```json
{
  "pack_size": 250
}
```

### Usage Analytics

#### GET /api/usage/stats
Get usage statistics for current user
```json
{
  "credits_remaining": 15,
  "credits_used_this_month": 5,
  "total_credits_used": 100,
  "tier": { ... },
  "tool_usage_breakdown": [
    { "tool": "agent_message", "count": 50 },
    { "tool": "get_ec2_instances", "count": 30 }
  ]
}
```

#### GET /api/usage/history
Get detailed usage logs with pagination
- Query params: `limit`, `offset`

## Database Schema

### New Tables

#### subscription_tiers
- `id` - Primary key
- `name` - Tier identifier (free, starter, professional, business)
- `display_name` - Human-readable name
- `monthly_price` - Price in USD
- `monthly_credits` - Credits allocated per month
- `description` - Tier description
- `features` - JSON array of features
- `is_active` - Whether tier is available

#### user_subscriptions
- `id` - Primary key
- `user_id` - Foreign key to users
- `tier_id` - Foreign key to subscription_tiers
- `credits_remaining` - Current credit balance
- `credits_used_this_month` - Usage this billing period
- `total_credits_used` - Lifetime usage
- `current_period_start` - Billing period start
- `current_period_end` - Billing period end
- `stripe_customer_id` - Stripe customer ID (optional)
- `stripe_subscription_id` - Stripe subscription ID (optional)
- `payment_status` - active, cancelled, past_due, unpaid

#### credit_purchases
- `id` - Primary key
- `user_id` - Foreign key to users
- `credits_amount` - Number of credits purchased
- `price_paid` - Amount paid in USD
- `stripe_payment_intent_id` - Stripe payment ID
- `payment_status` - pending, completed, failed, refunded
- `created_at` - Purchase timestamp
- `completed_at` - Completion timestamp

#### usage_logs
- `id` - Primary key
- `user_id` - Foreign key to users
- `conversation_id` - Foreign key to conversations
- `action_type` - Type of action (agent_message, tool_use)
- `tool_name` - Name of tool used (if applicable)
- `credits_used` - Credits consumed (default 1)
- `success` - Whether action succeeded
- `error_message` - Error details if failed
- `created_at` - Timestamp

## User Interface

### Billing Page

Access at `/billing` - Features:
- Current credit balance with visual progress bar
- Current tier badge
- Usage statistics (used X of Y this month)
- Next reset date
- All subscription tiers with upgrade buttons
- Credit pack purchase options
- Real-time updates after purchases

### Chat Interface Integration

The chat interface now displays:
- Credit count in response (returned with each message)
- Warning when credits are low (< 5 remaining)
- Error modal when out of credits with upgrade link

## Stripe Integration (Optional)

To enable real payment processing:

### 1. Get Stripe API Keys

Sign up at https://stripe.com and get your:
- Publishable key
- Secret key

### 2. Add to .env

```env
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

### 3. Create Stripe Products

In your Stripe Dashboard, create products for:
- Each subscription tier (with recurring pricing)
- Each credit pack (one-time payment)

### 4. Update Code

Replace the placeholder payment logic in:
- `/api/credits/purchase` - Use Stripe Payment Intents
- `/api/subscription/upgrade` - Use Stripe Subscriptions
- Add webhook handler at `/api/stripe/webhook`

Example Stripe integration:

```python
import stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

# Create subscription
@app.route('/api/subscription/upgrade', methods=['POST'])
@login_required
def upgrade_subscription():
    # ... existing validation ...

    # Create Stripe customer if doesn't exist
    if not subscription.stripe_customer_id:
        customer = stripe.Customer.create(
            email=current_user.email,
            metadata={'user_id': current_user.id}
        )
        subscription.stripe_customer_id = customer.id

    # Create Stripe subscription
    stripe_sub = stripe.Subscription.create(
        customer=subscription.stripe_customer_id,
        items=[{'price': tier.stripe_price_id}],
        metadata={'user_id': current_user.id}
    )

    subscription.stripe_subscription_id = stripe_sub.id
    # ... rest of logic ...
```

## Customization

### Adjusting Pricing

Edit `init_subscription_system.py` to modify:
- Tier prices
- Monthly credit amounts
- Tier features
- Credit pack pricing

Then run the script again to update the database.

### Changing Credit Cost per Action

Currently, each agent action costs 1 credit. To change:

1. Update `credits_used` in the UsageLog creation
2. Modify `use_credit()` to accept an amount parameter
3. Optionally charge different amounts for different tools

Example:
```python
# Heavy operations cost more
if tool_name in ['create_ec2_instance', 'create_rds_instance']:
    credits_to_use = 5
else:
    credits_to_use = 1

subscription.use_credit(credits_to_use)
```

### Adding Enterprise Tier

Add to `init_subscription_system.py`:
```python
{
    'name': 'enterprise',
    'display_name': 'Enterprise',
    'monthly_price': 499.0,
    'monthly_credits': 10000,
    'description': 'For large organizations',
    'features': [
        '10,000 agent actions per month',
        'White-label option',
        'SSO integration',
        # ... more features
    ]
}
```

## Monitoring & Analytics

### Track Revenue

```python
# Total revenue from subscriptions (monthly)
total_subscription_revenue = db.session.query(
    func.sum(SubscriptionTier.monthly_price)
).join(UserSubscription).filter(
    UserSubscription.payment_status == 'active'
).scalar()

# Total revenue from credit packs
total_pack_revenue = db.session.query(
    func.sum(CreditPurchase.price_paid)
).filter(
    CreditPurchase.payment_status == 'completed'
).scalar()
```

### Usage Reports

```python
# Most active users
top_users = db.session.query(
    User.username,
    func.sum(UsageLog.credits_used).label('total_used')
).join(UsageLog).group_by(User.id).order_by(
    desc('total_used')
).limit(10).all()

# Most used tools
top_tools = db.session.query(
    UsageLog.tool_name,
    func.count(UsageLog.id).label('count')
).group_by(UsageLog.tool_name).order_by(
    desc('count')
).limit(10).all()
```

## Testing

### Manual Testing

1. Create a test account
2. Check initial credits (should be 20)
3. Send messages and watch credits decrease
4. Try purchasing a credit pack
5. Try upgrading to a paid tier
6. Check usage stats at `/api/usage/stats`

### Automated Testing

```bash
pytest tests/test_credits_system.py
```

## Troubleshooting

### Users not getting credits

Run the initialization script again:
```bash
python init_subscription_system.py
```

### Credits not resetting

Check `current_period_end` dates in the database. The reset happens automatically on the next API call after the period expires.

### Database migration errors

If you get errors about missing columns, drop the database and recreate:
```bash
rm devops_agent.db
python app.py  # Will recreate tables
python init_subscription_system.py  # Will populate tiers
```

## Revenue Projections

Based on the pricing model:

### Conservative Estimate (100 users)
- 80 users on Free: $0
- 15 users on Starter ($19): $285/month
- 4 users on Professional ($79): $316/month
- 1 user on Business ($199): $199/month
- **Total MRR: $800/month**

### Growth Scenario (1,000 users)
- 700 users on Free: $0
- 200 users on Starter: $3,800/month
- 80 users on Professional: $6,320/month
- 20 users on Business: $3,980/month
- **Total MRR: $14,100/month**

Plus credit pack purchases (variable).

## Next Steps

1. ✅ Database models created
2. ✅ API endpoints implemented
3. ✅ Billing UI created
4. ✅ Credit deduction logic added
5. ✅ Usage tracking enabled
6. ⏳ Integrate Stripe for payments
7. ⏳ Add email notifications for low credits
8. ⏳ Create admin dashboard for monitoring
9. ⏳ Add usage analytics charts
10. ⏳ Implement team/organization features

## Support

For questions or issues with the credits system:
1. Check the logs in `logs/devops_agent.log`
2. Review usage in `/api/usage/history`
3. Check database directly with SQLite browser
4. Raise an issue on GitHub

---

**Built with ❤️ for sustainable SaaS monetization**
