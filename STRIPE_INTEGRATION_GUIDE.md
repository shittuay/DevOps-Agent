# Stripe Integration Guide

This guide will walk you through setting up and testing the Stripe payment integration for the DevOps Agent application.

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Stripe Dashboard Setup](#stripe-dashboard-setup)
3. [Create Products and Prices](#create-products-and-prices)
4. [Configure Environment Variables](#configure-environment-variables)
5. [Set Up Webhooks](#set-up-webhooks)
6. [Testing the Integration](#testing-the-integration)
7. [Going Live](#going-live)
8. [Troubleshooting](#troubleshooting)

---

## Prerequisites

- Stripe account (sign up at https://stripe.com)
- Python 3.8+ with dependencies installed
- Running DevOps Agent application

## Stripe Dashboard Setup

### 1. Get Your API Keys

1. Log in to your Stripe Dashboard: https://dashboard.stripe.com
2. Click on **Developers** in the left sidebar
3. Click on **API keys**
4. You'll see two keys:
   - **Publishable key** (starts with `pk_test_` or `pk_live_`)
   - **Secret key** (starts with `sk_test_` or `sk_live_`)

**IMPORTANT**: Use test keys for development/testing!

### 2. Enable Test Mode

- Toggle the "Test mode" switch in the top right corner of the dashboard
- This ensures you're working with test data and won't charge real money

---

## Create Products and Prices

You need to create products and prices in Stripe for both subscription tiers and credit packs.

### Subscription Tiers

Create 3 subscription products:

#### 1. Starter Tier
1. Go to **Products** > **Add product**
2. Fill in:
   - **Name**: Starter Plan
   - **Description**: 100 credits per month - Perfect for individuals
   - **Pricing**: Recurring
   - **Price**: $9.99 (or your chosen price)
   - **Billing period**: Monthly
3. Click **Save product**
4. Copy the **Price ID** (starts with `price_`) and save it for later

#### 2. Professional Tier
1. Create another product:
   - **Name**: Professional Plan
   - **Description**: 500 credits per month - For growing teams
   - **Price**: $29.99
   - **Billing period**: Monthly
2. Copy the **Price ID**

#### 3. Business Tier
1. Create another product:
   - **Name**: Business Plan
   - **Description**: 2000 credits per month - For enterprises
   - **Price**: $99.99
   - **Billing period**: Monthly
2. Copy the **Price ID**

### Credit Packs (One-Time Purchases)

Create 4 one-time purchase products:

#### 1. 100 Credits Pack
1. Go to **Products** > **Add product**
2. Fill in:
   - **Name**: 100 Credits
   - **Description**: One-time purchase of 100 credits
   - **Pricing**: One-time
   - **Price**: $10.00
3. Copy the **Price ID**

#### 2. 250 Credits Pack
- **Name**: 250 Credits
- **Price**: $20.00
- Copy the **Price ID**

#### 3. 500 Credits Pack
- **Name**: 500 Credits
- **Price**: $35.00
- Copy the **Price ID**

#### 4. 1000 Credits Pack
- **Name**: 1000 Credits
- **Price**: $60.00
- Copy the **Price ID**

---

## Configure Environment Variables

Edit your `config/.env` file with the values you collected:

```bash
# Stripe API Keys (from Step 1)
STRIPE_SECRET_KEY=sk_test_your_secret_key_here
STRIPE_PUBLISHABLE_KEY=pk_test_your_publishable_key_here

# Application URL (important for redirects)
BASE_URL=http://localhost:5000

# Subscription Price IDs (from Step 2)
STRIPE_PRICE_STARTER=price_1234567890abcdefghijklmn
STRIPE_PRICE_PROFESSIONAL=price_abcdefghijklmnopqrstuvwx
STRIPE_PRICE_BUSINESS=price_zyxwvutsrqponmlkjihgfedcb

# Credit Pack Price IDs (from Step 3)
STRIPE_PRICE_PACK_100=price_100credits123456789
STRIPE_PRICE_PACK_250=price_250credits123456789
STRIPE_PRICE_PACK_500=price_500credits123456789
STRIPE_PRICE_PACK_1000=price_1000credits123456789
```

**Note**: The webhook secret will be added in the next step.

---

## Set Up Webhooks

Webhooks allow Stripe to notify your application about payment events.

### For Local Development (Using Stripe CLI)

1. **Install Stripe CLI**: https://stripe.com/docs/stripe-cli

2. **Login to Stripe**:
   ```bash
   stripe login
   ```

3. **Forward webhooks to your local server**:
   ```bash
   stripe listen --forward-to localhost:5000/api/stripe/webhook
   ```

4. The CLI will output a webhook signing secret (starts with `whsec_`). Copy this and add to your `.env`:
   ```bash
   STRIPE_WEBHOOK_SECRET=whsec_1234567890abcdefghijklmnopqrstuvwxyz
   ```

### For Production (Using Stripe Dashboard)

1. Go to **Developers** > **Webhooks**
2. Click **Add endpoint**
3. Enter your endpoint URL: `https://yourdomain.com/api/stripe/webhook`
4. Select events to listen for:
   - `checkout.session.completed`
   - `invoice.payment_succeeded`
   - `customer.subscription.deleted`
   - `customer.subscription.updated`
5. Copy the **Signing secret** and add it to your production `.env` file

---

## Testing the Integration

### 1. Start Your Application

```bash
python app.py
```

The application should now be running at http://localhost:5000

### 2. Start Stripe CLI (for local testing)

In a separate terminal:
```bash
stripe listen --forward-to localhost:5000/api/stripe/webhook
```

### 3. Test Subscription Purchase

1. Navigate to http://localhost:5000/billing
2. Click on a subscription tier (Starter, Professional, or Business)
3. You'll be redirected to Stripe Checkout
4. Use test card numbers:
   - **Success**: `4242 4242 4242 4242`
   - **Decline**: `4000 0000 0000 0002`
   - **3D Secure**: `4000 0025 0000 3155`
5. Use any future expiration date (e.g., 12/34)
6. Use any 3-digit CVC (e.g., 123)
7. Use any billing ZIP code (e.g., 12345)
8. Complete the checkout

### 4. Test Credit Pack Purchase

1. Navigate to the credits section on the billing page
2. Click "Buy Now" on a credit pack
3. Complete checkout with test card: `4242 4242 4242 4242`

### 5. Verify in Stripe Dashboard

1. Go to **Payments** in Stripe Dashboard
2. You should see your test payment
3. Go to **Customers** to see the created customer
4. Go to **Subscriptions** to see active subscriptions

### 6. Check Webhook Events

In the Stripe CLI terminal, you should see webhook events being received:
```
✔ Received event: checkout.session.completed
✔ Received event: invoice.payment_succeeded
```

### 7. Verify in Application Database

The application should have:
- Updated the user's subscription tier
- Added credits to the user's account
- Created purchase records in the database

---

## Going Live

When you're ready to accept real payments:

### 1. Switch to Live Mode

1. Toggle off "Test mode" in Stripe Dashboard
2. Get your **live** API keys from **Developers** > **API keys**
3. Update your `.env` file with live keys:
   ```bash
   STRIPE_SECRET_KEY=sk_live_your_live_secret_key
   STRIPE_PUBLISHABLE_KEY=pk_live_your_live_publishable_key
   ```

### 2. Create Live Products

Repeat the product creation process in live mode (same prices and configurations).

### 3. Set Up Live Webhooks

1. Go to **Developers** > **Webhooks** (in live mode)
2. Add your production endpoint
3. Update `STRIPE_WEBHOOK_SECRET` with the live webhook secret

### 4. Update BASE_URL

Update your `.env` with your production URL:
```bash
BASE_URL=https://yourdomain.com
```

### 5. Complete Stripe Activation

1. Fill out your business details in Stripe Dashboard
2. Activate your Stripe account
3. Connect your bank account for payouts

---

## Troubleshooting

### Issue: "Stripe not enabled" error

**Solution**: Make sure `stripe` is installed:
```bash
pip install stripe python-dateutil
```

### Issue: Webhooks not being received

**Solution**:
- Check that Stripe CLI is running and forwarding to the correct URL
- Verify the webhook secret is correct in `.env`
- Check application logs for webhook errors

### Issue: Invalid price ID error

**Solution**:
- Verify all price IDs in `.env` are correct
- Make sure you're in the right mode (test/live)
- Price IDs start with `price_` not `prod_`

### Issue: Checkout session not creating

**Solution**:
- Check that Stripe secret key is valid
- Verify BASE_URL is set correctly
- Check application logs for detailed error messages

### Issue: Credits not being added after payment

**Solution**:
- Ensure webhooks are properly configured
- Check the webhook endpoint is receiving events
- Verify the webhook secret is correct
- Check database for transaction records

### Issue: Test payments showing in production

**Solution**:
- Make sure you're using test keys in development
- Verify "Test mode" toggle is ON in Stripe Dashboard
- Test keys start with `sk_test_` and `pk_test_`

---

## Additional Resources

- **Stripe Documentation**: https://stripe.com/docs
- **Stripe CLI Documentation**: https://stripe.com/docs/stripe-cli
- **Testing Cards**: https://stripe.com/docs/testing
- **Webhooks Guide**: https://stripe.com/docs/webhooks
- **Checkout Session**: https://stripe.com/docs/payments/checkout

---

## Security Best Practices

1. **Never commit your secret keys to version control**
2. Use environment variables for all sensitive data
3. Use test keys for development and staging
4. Validate webhook signatures (already implemented)
5. Keep your Stripe library up to date
6. Monitor failed payments and suspicious activity
7. Use HTTPS in production
8. Implement rate limiting on payment endpoints

---

## Support

If you encounter issues:

1. Check Stripe Dashboard logs: **Developers** > **Logs**
2. Check application logs
3. Review Stripe's status page: https://status.stripe.com
4. Contact Stripe support: https://support.stripe.com

---

## Summary

You've successfully integrated Stripe with your DevOps Agent application! Users can now:

- Subscribe to monthly plans (Starter, Professional, Business)
- Purchase one-time credit packs
- Have their credits automatically managed
- Receive proper payment confirmations

The integration handles:
- Secure checkout sessions
- Webhook event processing
- Subscription management
- Credit tracking
- Payment history

Happy building!
