# Stripe Integration - Quick Start Guide

Get your Stripe payment integration up and running in 5 minutes!

## Prerequisites

- Stripe account (sign up at https://stripe.com)
- Stripe API key (already configured in your `.env` file)

## Quick Setup (Automated)

### Step 1: Run the Product Setup Script

This script will automatically create all necessary products and prices in Stripe:

```bash
python setup_stripe_products.py
```

The script will:
- Create 3 subscription tiers (Starter, Professional, Business)
- Create 4 credit packs (100, 250, 500, 1000 credits)
- Generate the Price IDs for your `.env` file

### Step 2: Update Your .env File

Copy the generated Price IDs from the script output and paste them into `config/.env`:

```bash
STRIPE_PRICE_STARTER=price_xxxxxxxxxxxxx
STRIPE_PRICE_PROFESSIONAL=price_xxxxxxxxxxxxx
STRIPE_PRICE_BUSINESS=price_xxxxxxxxxxxxx
STRIPE_PRICE_PACK_100=price_xxxxxxxxxxxxx
STRIPE_PRICE_PACK_250=price_xxxxxxxxxxxxx
STRIPE_PRICE_PACK_500=price_xxxxxxxxxxxxx
STRIPE_PRICE_PACK_1000=price_xxxxxxxxxxxxx
```

### Step 3: Set Up Webhooks (Local Testing)

Install and run the Stripe CLI to receive webhook events locally:

```bash
# Install Stripe CLI (one-time)
# Download from: https://stripe.com/docs/stripe-cli

# Login to Stripe
stripe login

# Forward webhooks to your local server
stripe listen --forward-to localhost:5000/api/stripe/webhook
```

Copy the webhook signing secret (starts with `whsec_`) and add it to your `.env`:

```bash
STRIPE_WEBHOOK_SECRET=whsec_xxxxxxxxxxxxx
```

### Step 4: Test the Integration

Run the test script to verify everything is working:

```bash
python test_stripe.py
```

You should see all tests passing!

### Step 5: Start Your Application

```bash
python app.py
```

Navigate to http://localhost:5000/billing and test a payment!

## Testing Payments

Use these test card numbers in Stripe Checkout:

| Card Number | Description |
|-------------|-------------|
| 4242 4242 4242 4242 | Success |
| 4000 0000 0000 0002 | Card declined |
| 4000 0025 0000 3155 | Requires 3D Secure |

- Use any future expiration date (e.g., 12/34)
- Use any 3-digit CVC (e.g., 123)
- Use any billing ZIP code (e.g., 12345)

## What's Included

Your Stripe integration includes:

✅ **Subscription Management**
- Starter Plan: $9.99/month (100 credits)
- Professional Plan: $29.99/month (500 credits)
- Business Plan: $99.99/month (2000 credits)

✅ **Credit Packs**
- 100 Credits: $10.00
- 250 Credits: $20.00
- 500 Credits: $35.00
- 1000 Credits: $60.00

✅ **Automatic Features**
- Secure checkout with Stripe Checkout
- Automatic credit allocation
- Webhook event handling
- Subscription management
- Payment history tracking

## File Structure

```
devops-agent/
├── stripe_integration.py          # Stripe service layer
├── setup_stripe_products.py       # Product creation helper
├── test_stripe.py                 # Integration tests
├── STRIPE_INTEGRATION_GUIDE.md    # Detailed documentation
├── STRIPE_QUICKSTART.md          # This file
└── config/
    └── .env                       # Stripe configuration
```

## Troubleshooting

### "Stripe not enabled" error
```bash
pip install stripe python-dateutil
```

### Products not found
Make sure you've run `setup_stripe_products.py` and updated your `.env` file.

### Webhooks not working
- Check that Stripe CLI is running: `stripe listen --forward-to localhost:5000/api/stripe/webhook`
- Verify webhook secret is correct in `.env`

### Credits not added after payment
- Check webhook events in Stripe CLI terminal
- Check application logs for errors
- Verify webhook secret matches

## Production Deployment

When ready to go live:

1. **Switch to Live Mode** in Stripe Dashboard
2. **Get live API keys** and update `.env`
3. **Run product setup again** in live mode:
   ```bash
   python setup_stripe_products.py
   ```
4. **Set up production webhooks** in Stripe Dashboard
5. **Update BASE_URL** in `.env` to your domain

## Resources

- **Detailed Guide**: See `STRIPE_INTEGRATION_GUIDE.md`
- **Stripe Dashboard**: https://dashboard.stripe.com
- **Stripe Docs**: https://stripe.com/docs
- **Test Cards**: https://stripe.com/docs/testing

## Support

If you run into issues:
1. Check `test_stripe.py` output for specific errors
2. Review Stripe Dashboard logs
3. Check application logs
4. See `STRIPE_INTEGRATION_GUIDE.md` for detailed troubleshooting

---

**You're all set!** Your Stripe integration is ready to accept payments. 🎉
