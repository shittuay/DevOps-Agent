# Quick Setup Guide - Credits System

## 5-Minute Setup

Follow these steps to get your credits-based monetization system running:

### Step 1: Install Dependencies (30 seconds)

```bash
pip install python-dateutil stripe
```

### Step 2: Initialize Database (1 minute)

```bash
python init_subscription_system.py
```

You should see output like:
```
DevOps Agent - Subscription System Initialization
Creating subscription tiers...
  Creating tier 'Free Tier'...
  Creating tier 'Starter'...
  Creating tier 'Professional'...
  Creating tier 'Business'...
Subscription tiers set up successfully!

Migrating existing users to subscription system...
Migration complete! 0 users migrated to free tier.

SUBSCRIPTION SYSTEM SUMMARY
Active Subscription Tiers: 4
...
```

### Step 3: Start the Application (30 seconds)

```bash
python app.py
```

### Step 4: Test the System (3 minutes)

1. **Create a Test Account**
   - Go to `http://localhost:5000/signup`
   - Create a new account
   - You'll automatically get 20 free credits

2. **Check Your Credits**
   - Go to `http://localhost:5000/billing`
   - You should see:
     - 20 credits remaining
     - Free Tier badge
     - All subscription tiers
     - Credit pack options

3. **Use Some Credits**
   - Go to `http://localhost:5000/chat`
   - Send a message to the agent
   - Watch your credits decrease to 19
   - Each message costs 1 credit

4. **Test Low Credits Warning**
   - Send 15 more messages (to get down to 4 credits)
   - You'll see a yellow warning banner
   - "Low Credits Warning - Only 4 credits remaining"

5. **Test Out of Credits**
   - Send 4 more messages
   - You'll see a modal blocking further use
   - "Out of Credits - Upgrade or Purchase"

### Step 5: Test Credit Purchase (1 minute)

1. Go to `/billing`
2. Click "Buy Now" on any credit pack
3. Confirm the purchase
4. Credits are added instantly
5. Go back to chat and continue using

**Note:** Payment processing is simulated. See "Stripe Integration" section to enable real payments.

---

## What You Get

### ✅ Completed Features

1. **4 Subscription Tiers**
   - Free (20 credits/month)
   - Starter ($19, 200 credits)
   - Professional ($79, 1000 credits)
   - Business ($199, 3000 credits)

2. **Credit Packs**
   - 100 credits for $10
   - 250 credits for $20
   - 500 credits for $35
   - 1000 credits for $60

3. **Credit Deduction**
   - Automatic deduction before each agent action
   - Returns error when out of credits
   - Prevents usage without credits

4. **Monthly Reset**
   - Automatic credit refresh each billing period
   - Tracks period start/end dates
   - Resets usage counters

5. **Usage Tracking**
   - Complete usage logs
   - Per-user analytics
   - Tool-level breakdown

6. **UI Components**
   - Billing dashboard (`/billing`)
   - Credit warnings
   - Out of credits modal
   - Upgrade prompts

7. **API Endpoints**
   - `/api/subscription` - Get subscription
   - `/api/subscription/upgrade` - Upgrade tier
   - `/api/credits/purchase` - Buy credits
   - `/api/usage/stats` - Usage analytics
   - `/api/usage/history` - Detailed logs

---

## Testing Scenarios

### Scenario 1: New User Journey

```bash
# 1. Sign up
curl -X POST http://localhost:5000/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","username":"testuser","password":"password123"}'

# 2. Check credits
curl http://localhost:5000/api/subscription -H "Cookie: session=..."

# Expected: 20 credits, Free tier
```

### Scenario 2: Upgrade to Paid Tier

```bash
# Get available tiers
curl http://localhost:5000/api/subscription/tiers

# Upgrade to Starter (tier_id = 2)
curl -X POST http://localhost:5000/api/subscription/upgrade \
  -H "Content-Type: application/json" \
  -H "Cookie: session=..." \
  -d '{"tier_id": 2}'

# Expected: 200 credits, Starter tier
```

### Scenario 3: Purchase Credit Pack

```bash
# Buy 250 credits
curl -X POST http://localhost:5000/api/credits/purchase \
  -H "Content-Type: application/json" \
  -H "Cookie: session=..." \
  -d '{"pack_size": 250}'

# Expected: Credits added, purchase record created
```

### Scenario 4: Monthly Reset

```python
# Simulate month passing
from app import app, db
from models import UserSubscription
from datetime import datetime, timedelta

with app.app_context():
    sub = UserSubscription.query.first()

    # Set period end to yesterday
    sub.current_period_end = datetime.utcnow() - timedelta(days=1)
    db.session.commit()

    # Next API call will trigger reset
    # Credits will be restored to tier's monthly amount
```

---

## Customization Options

### Change Pricing

Edit `init_subscription_system.py`:

```python
{
    'name': 'starter',
    'monthly_price': 29.0,  # Changed from 19
    'monthly_credits': 300,  # Changed from 200
}
```

Run again: `python init_subscription_system.py`

### Change Credit Cost per Action

Edit `app.py` in the `/api/chat` endpoint:

```python
# Make expensive operations cost more
credits_to_use = 1  # Default

if 'create' in message.lower() or 'deploy' in message.lower():
    credits_to_use = 5

subscription.use_credit(credits_to_use)
```

### Add New Tier

Add to `init_subscription_system.py`:

```python
{
    'name': 'enterprise',
    'display_name': 'Enterprise',
    'monthly_price': 499.0,
    'monthly_credits': 10000,
    'description': 'For large organizations',
    'features': ['10,000 credits', 'White-label', 'SSO']
}
```

---

## Monitoring

### Check Total Revenue

```python
from app import app, db
from models import UserSubscription, SubscriptionTier, CreditPurchase
from sqlalchemy import func

with app.app_context():
    # Monthly recurring revenue
    mrr = db.session.query(
        func.sum(SubscriptionTier.monthly_price)
    ).join(UserSubscription).filter(
        UserSubscription.payment_status == 'active'
    ).scalar()

    print(f"MRR: ${mrr}")

    # Total from credit packs
    pack_revenue = db.session.query(
        func.sum(CreditPurchase.price_paid)
    ).filter(
        CreditPurchase.payment_status == 'completed'
    ).scalar()

    print(f"Credit Pack Revenue: ${pack_revenue}")
```

### Check Active Subscriptions

```python
from models import UserSubscription, SubscriptionTier

with app.app_context():
    tiers = db.session.query(
        SubscriptionTier.display_name,
        func.count(UserSubscription.id).label('count')
    ).join(UserSubscription).group_by(
        SubscriptionTier.id
    ).all()

    for tier_name, count in tiers:
        print(f"{tier_name}: {count} subscribers")
```

### Top Users by Usage

```python
from models import User, UsageLog

with app.app_context():
    top = db.session.query(
        User.username,
        func.sum(UsageLog.credits_used).label('total')
    ).join(UsageLog).group_by(
        User.id
    ).order_by(desc('total')).limit(10).all()

    for username, total in top:
        print(f"{username}: {total} credits used")
```

---

## Troubleshooting

### "Subscription system not initialized"

**Problem:** Tiers not in database

**Solution:**
```bash
python init_subscription_system.py
```

### Credits not deducting

**Problem:** Old code cached

**Solution:**
```bash
# Stop app
# Ctrl+C

# Restart
python app.py
```

### Database locked error

**Problem:** SQLite locked by another process

**Solution:**
```bash
# Kill any running app instances
pkill -f app.py

# Restart
python app.py
```

### Users stuck at 0 credits

**Problem:** Period end date not set

**Solution:**
```python
from app import app, db
from models import UserSubscription
from datetime import datetime
from dateutil.relativedelta import relativedelta

with app.app_context():
    subs = UserSubscription.query.all()
    for sub in subs:
        if not sub.current_period_end:
            sub.current_period_end = datetime.utcnow() + relativedelta(months=1)
    db.session.commit()
```

---

## Next Steps

### Enable Stripe Payments

1. Sign up at https://stripe.com
2. Get API keys from Dashboard
3. Add to `config/.env`:
   ```
   STRIPE_SECRET_KEY=sk_test_...
   STRIPE_PUBLISHABLE_KEY=pk_test_...
   ```
4. See `CREDITS_SYSTEM.md` for integration code

### Add Email Notifications

```python
# Install flask-mail
pip install flask-mail

# Send low credits email
from flask_mail import Message

def send_low_credits_email(user):
    msg = Message(
        'Low Credits Warning',
        recipients=[user.email],
        body=f'Hi {user.username}, you only have {user.subscription.credits_remaining} credits left.'
    )
    mail.send(msg)
```

### Create Admin Dashboard

Add route in `app.py`:

```python
@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    # Check if user is admin
    if current_user.email != 'admin@example.com':
        return 'Unauthorized', 403

    stats = {
        'total_users': User.query.count(),
        'active_subs': UserSubscription.query.filter_by(payment_status='active').count(),
        'mrr': calculate_mrr(),
        'total_credits_used': db.session.query(func.sum(UsageLog.credits_used)).scalar()
    }

    return render_template('admin_dashboard.html', stats=stats)
```

---

## Support

Questions? Check:
1. `CREDITS_SYSTEM.md` - Full documentation
2. Logs: `logs/devops_agent.log`
3. Database: `devops_agent.db` (use SQLite browser)

---

**You're all set! 🎉**

Your DevOps Agent now has a complete monetization system. Start getting paid for your API and hosting costs!
