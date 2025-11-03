# Stripe Integration Setup Guide

## Overview

This guide will help you set up Stripe payments for your DevOps Agent, enabling real payment processing for subscriptions and credit packs.

---

## Prerequisites

- Stripe account (sign up at https://stripe.com)
- DevOps Agent application running
- Access to your server for webhook configuration

---

## Step 1: Create Stripe Account & Get API Keys

### 1.1 Sign Up for Stripe

1. Go to https://stripe.com
2. Click "Sign up"
3. Complete registration
4. Verify your email

### 1.2 Get Your API Keys

1. Log in to Stripe Dashboard: https://dashboard.stripe.com
2. Click "Developers" in the left sidebar
3. Click "API keys"
4. Copy your keys:
   - **Publishable key** (starts with `pk_test_` for test mode)
   - **Secret key** (starts with `sk_test_` for test mode)

### 1.3 Add Keys to Your .env File

Edit `config/.env` and add:

```env
STRIPE_SECRET_KEY=sk_test_your_actual_secret_key_here
STRIPE_PUBLISHABLE_KEY=pk_test_your_actual_publishable_key_here
```

---

## Step 2: Create Products and Prices in Stripe

### 2.1 Create Subscription Products

#### Product 1: Starter Plan

1. In Stripe Dashboard, go to **Products** → **Add product**
2. Fill in:
   - **Name**: DevOps Agent - Starter
   - **Description**: 200 credits per month for individual developers
3. Click **Add pricing**:
   - **Type**: Recurring
   - **Price**: $19.00
   - **Billing period**: Monthly
   - **Currency**: USD
4. Click **Save product**
5. Copy the **Price ID** (starts with `price_`)
6. Add to `.env`:
   ```env
   STRIPE_PRICE_STARTER=price_your_starter_price_id_here
   ```

#### Product 2: Professional Plan

1. **Name**: DevOps Agent - Professional
2. **Description**: 1,000 credits per month for growing teams
3. **Price**: $79.00 / monthly
4. Copy Price ID and add to `.env`:
   ```env
   STRIPE_PRICE_PROFESSIONAL=price_your_professional_price_id_here
   ```

#### Product 3: Business Plan

1. **Name**: DevOps Agent - Business
2. **Description**: 3,000 credits per month for enterprises
3. **Price**: $199.00 / monthly
4. Copy Price ID and add to `.env`:
   ```env
   STRIPE_PRICE_BUSINESS=price_your_business_price_id_here
   ```

### 2.2 Create One-Time Credit Packs

#### Pack 1: 100 Credits

1. Go to **Products** → **Add product**
2. Fill in:
   - **Name**: 100 Credits Pack
   - **Description**: One-time purchase of 100 credits
3. Click **Add pricing**:
   - **Type**: One-time
   - **Price**: $10.00
   - **Currency**: USD
4. Copy Price ID:
   ```env
   STRIPE_PRICE_PACK_100=price_your_100_pack_id_here
   ```

#### Pack 2: 250 Credits

- **Name**: 250 Credits Pack
- **Price**: $20.00 (one-time)
- Add to `.env`:
  ```env
  STRIPE_PRICE_PACK_250=price_your_250_pack_id_here
  ```

#### Pack 3: 500 Credits

- **Name**: 500 Credits Pack
- **Price**: $35.00 (one-time)
- Add to `.env`:
  ```env
  STRIPE_PRICE_PACK_500=price_your_500_pack_id_here
  ```

#### Pack 4: 1000 Credits

- **Name**: 1000 Credits Pack
- **Price**: $60.00 (one-time)
- Add to `.env`:
  ```env
  STRIPE_PRICE_PACK_1000=price_your_1000_pack_id_here
  ```

---

## Step 3: Configure Webhooks

Webhooks notify your app when payments succeed or subscriptions are cancelled.

### 3.1 Create Webhook Endpoint

1. In Stripe Dashboard, go to **Developers** → **Webhooks**
2. Click **Add endpoint**
3. **Endpoint URL**:
   ```
   https://your-domain.com/api/stripe/webhook
   ```
   *For local testing, see "Testing with Stripe CLI" below*

4. **Select events to listen to**:
   - `checkout.session.completed`
   - `invoice.payment_succeeded`
   - `customer.subscription.deleted`

5. Click **Add endpoint**

### 3.2 Get Webhook Secret

1. Click on your newly created webhook
2. Click **Reveal** next to "Signing secret"
3. Copy the secret (starts with `whsec_`)
4. Add to `.env`:
   ```env
   STRIPE_WEBHOOK_SECRET=whsec_your_webhook_secret_here
   ```

---

## Step 4: Testing Locally (Optional)

### 4.1 Install Stripe CLI

Download from: https://stripe.com/docs/stripe-cli

### 4.2 Login

```bash
stripe login
```

### 4.3 Forward Webhooks to Localhost

```bash
stripe listen --forward-to localhost:5000/api/stripe/webhook
```

This will give you a webhook secret for local testing. Use it temporarily in `.env`.

### 4.4 Trigger Test Events

```bash
# Test successful payment
stripe trigger checkout.session.completed

# Test subscription cancellation
stripe trigger customer.subscription.deleted
```

---

## Step 5: Test Stripe Integration

### 5.1 Restart Your Application

```bash
# Stop the app (Ctrl+C)
# Start it again
python app.py
```

### 5.2 Test Subscription Upgrade

1. Go to http://localhost:5000/billing
2. Click **Upgrade** on any tier
3. You should be redirected to Stripe Checkout
4. Use test card: `4242 4242 4242 4242`
   - Expiry: Any future date
   - CVC: Any 3 digits
   - ZIP: Any 5 digits
5. Complete payment
6. You should be redirected back with success message
7. Credits should be added to your account

### 5.3 Test Credit Pack Purchase

1. Go to http://localhost:5000/billing
2. Click **Buy Now** on any credit pack
3. Use same test card
4. Complete payment
5. Verify credits were added

---

## Step 6: Go Live (Production)

### 6.1 Activate Your Stripe Account

1. Complete Stripe account verification
2. Add business details
3. Add bank account for payouts

### 6.2 Switch to Live Mode

1. In Stripe Dashboard, toggle **Test mode** OFF
2. Get your **live API keys**:
   - Go to **Developers** → **API keys**
   - Copy live keys (start with `pk_live_` and `sk_live_`)

### 6.3 Update .env with Live Keys

```env
STRIPE_SECRET_KEY=sk_live_your_live_secret_key
STRIPE_PUBLISHABLE_KEY=pk_live_your_live_publishable_key
```

### 6.4 Create Live Products & Prices

Repeat Step 2 in **Live mode** to create:
- 3 subscription products (Starter, Professional, Business)
- 4 credit pack products (100, 250, 500, 1000)

Update `.env` with **live Price IDs**.

### 6.5 Update Live Webhook

1. In **Live mode**, create webhook endpoint
2. Point to your production URL:
   ```
   https://yourdomain.com/api/stripe/webhook
   ```
3. Select same events
4. Copy live webhook secret
5. Update `.env`:
   ```env
   STRIPE_WEBHOOK_SECRET=whsec_your_live_webhook_secret
   ```

---

## Step 7: Monitor Payments

### 7.1 Stripe Dashboard

Monitor in real-time:
- https://dashboard.stripe.com/payments
- https://dashboard.stripe.com/subscriptions

### 7.2 Application Logs

Check your app logs:
```bash
tail -f logs/devops_agent.log
```

Look for:
- "Received Stripe webhook: checkout.session.completed"
- "Subscription created/updated for user X"
- "Credit pack (250) purchased for user X"

---

## Troubleshooting

### Issue: "Payment processing is not enabled"

**Solution**: Stripe package not installed
```bash
pip install stripe
```

### Issue: "Failed to create checkout session"

**Causes**:
1. Price ID not set or incorrect in `.env`
2. Stripe API key invalid

**Solution**:
- Verify all Price IDs in `.env`
- Check API keys are correct
- Ensure no extra spaces in `.env` values

### Issue: Webhook not triggering

**Causes**:
1. Webhook secret incorrect
2. Webhook URL not accessible
3. Events not selected

**Solution**:
- Verify webhook secret in `.env`
- Test webhook endpoint: `curl https://yourdomain.com/api/stripe/webhook`
- Check webhook logs in Stripe Dashboard

### Issue: Credits not added after payment

**Causes**:
1. Webhook not received
2. Email mismatch
3. Database error

**Solution**:
- Check webhook logs in Stripe Dashboard → Webhooks → Your endpoint
- Verify user email matches checkout email
- Check application logs for errors

---

## Security Best Practices

### 1. Never Commit API Keys

Add to `.gitignore`:
```
config/.env
*.env
```

### 2. Use Environment Variables

Never hardcode keys in code:
```python
# ❌ BAD
stripe.api_key = "sk_test_abc123"

# ✅ GOOD
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
```

### 3. Verify Webhook Signatures

Our code already does this:
```python
stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
```

### 4. Use HTTPS in Production

Stripe requires HTTPS for webhooks. Use:
- Let's Encrypt (free SSL)
- Cloudflare
- Your hosting provider's SSL

---

## Pricing Recommendations

### Monthly Subscriptions

| Tier | Credits | Price | Target |
|------|---------|-------|--------|
| Free | 20 | $0 | Trials |
| Starter | 200 | $19 | Individuals |
| Professional | 1,000 | $79 | Teams |
| Business | 3,000 | $199 | Enterprises |

### Credit Packs

| Pack | Price | Per Credit | Discount |
|------|-------|-----------|----------|
| 100 | $10 | $0.10 | 0% |
| 250 | $20 | $0.08 | 20% |
| 500 | $35 | $0.07 | 30% |
| 1000 | $60 | $0.06 | 40% |

---

## Revenue Projections

### Conservative (100 paying users)

- 50 Starter ($19) = $950/mo
- 30 Professional ($79) = $2,370/mo
- 20 Business ($199) = $3,980/mo

**MRR**: $7,300
**ARR**: $87,600

### Growth (1,000 paying users)

- 500 Starter = $9,500/mo
- 300 Professional = $23,700/mo
- 200 Business = $39,800/mo

**MRR**: $73,000
**ARR**: $876,000

*Plus one-time credit pack sales*

---

## Support & Resources

### Stripe Documentation
- Checkout: https://stripe.com/docs/payments/checkout
- Subscriptions: https://stripe.com/docs/billing/subscriptions
- Webhooks: https://stripe.com/docs/webhooks

### Your Application
- Billing page: http://localhost:5000/billing
- Webhook endpoint: /api/stripe/webhook
- Logs: logs/devops_agent.log

### Getting Help
1. Check Stripe Dashboard → Logs
2. Check your application logs
3. Test with Stripe CLI
4. Contact Stripe support (excellent!)

---

## Quick Reference: .env Template

```env
# Stripe Payment Configuration
STRIPE_SECRET_KEY=sk_test_51ABC...
STRIPE_PUBLISHABLE_KEY=pk_test_51ABC...
STRIPE_WEBHOOK_SECRET=whsec_abc123...

# Subscription Price IDs
STRIPE_PRICE_STARTER=price_1ABC123...
STRIPE_PRICE_PROFESSIONAL=price_1DEF456...
STRIPE_PRICE_BUSINESS=price_1GHI789...

# Credit Pack Price IDs
STRIPE_PRICE_PACK_100=price_1JKL012...
STRIPE_PRICE_PACK_250=price_1MNO345...
STRIPE_PRICE_PACK_500=price_1PQR678...
STRIPE_PRICE_PACK_1000=price_1STU901...
```

---

**🎉 Congratulations! Your DevOps Agent is now ready to accept real payments!**

Start with test mode, then switch to live mode when ready. Monitor your Stripe Dashboard and application logs to ensure everything works smoothly.

Good luck with your SaaS business! 💰
