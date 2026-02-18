# Local Testing Guide - Stripe Integration

## ✅ Your Application is Running!

Your Flask application is now running at: **http://localhost:5000**

All Stripe products have been created and configured.

---

## 🧪 Testing Steps

### Step 1: Access the Billing Page

1. Open your web browser
2. Navigate to: **http://localhost:5000**
3. Log in with your account (username: `shittyu`)
4. Click on "Billing" in the navigation menu or go directly to: **http://localhost:5000/billing**

### Step 2: View Your Current Status

On the billing page, you should see:
- Your current subscription tier: **Starter**
- Your available credits: **200 credits**
- Subscription plans available for upgrade
- Credit packs available for purchase

### Step 3: Test Subscription Upgrade (Optional)

**⚠️ IMPORTANT: You're using LIVE Stripe keys, so this will create a real payment!**

If you want to test without real money, you should:
1. Get test keys from Stripe Dashboard (starts with `sk_test_` and `pk_test_`)
2. Update `config/.env` with test keys
3. Restart the application

**To test subscription upgrade:**
1. Click "Upgrade" on Professional or Business tier
2. You'll be redirected to Stripe Checkout
3. **For TEST mode**: Use card `4242 4242 4242 4242`
   - Expiry: Any future date (e.g., 12/34)
   - CVC: Any 3 digits (e.g., 123)
   - ZIP: Any 5 digits (e.g., 12345)
4. Complete the payment
5. You'll be redirected back to the billing page
6. Your credits should be updated

### Step 4: Test Credit Pack Purchase

**To test credit pack purchase:**
1. Scroll to "Buy More Credits" section
2. Click "Buy Now" on any credit pack (e.g., 100 Credits for $10)
3. Confirm the purchase
4. You'll be redirected to Stripe Checkout
5. **For TEST mode**: Use test card `4242 4242 4242 4242`
6. Complete the payment
7. You'll be redirected back with a success message
8. Your credits should be updated

---

## 🔧 Set Up Webhooks (Required for Credits to Work)

Webhooks are needed to automatically add credits after payment. Here's how to set them up:

### Option 1: Using Stripe CLI (Recommended for Local Testing)

1. **Install Stripe CLI** (if not already installed):
   - Download from: https://stripe.com/docs/stripe-cli
   - Or use: `winget install stripe`

2. **Login to Stripe**:
   ```bash
   stripe login
   ```

3. **Forward webhooks to your local server** (in a new terminal):
   ```bash
   stripe listen --forward-to localhost:5000/api/stripe/webhook
   ```

4. **Copy the webhook secret** from the output (starts with `whsec_`)

5. **Update your .env file**:
   - Open `config/.env`
   - Find `STRIPE_WEBHOOK_SECRET=`
   - Paste your webhook secret

6. **Keep the Stripe CLI running** while testing

### Option 2: Testing Without Webhooks

If you don't set up webhooks, payments will complete but credits won't be added automatically. You can still:
- Test the checkout flow
- Verify payments in Stripe Dashboard
- Manually add credits via database if needed

---

## 📊 What to Look For

### Success Indicators:

1. **Checkout Session Created**:
   - You get redirected to Stripe Checkout
   - The correct amount is shown
   - Product description is visible

2. **Payment Successful**:
   - Payment completes without errors
   - You're redirected back to `/billing/success`
   - You see a success message

3. **Credits Added** (requires webhooks):
   - Your credit balance increases
   - Payment appears in history
   - Subscription tier updates (for subscription purchases)

### Application Logs:

Watch the terminal where Flask is running. You should see:
```
Received Stripe webhook: checkout.session.completed
Subscription created/updated for user X
Credit pack (100) purchased for user X
```

---

## 🧾 Test Cards for Stripe

### Successful Payments:
- **Visa**: `4242 4242 4242 4242`
- **Mastercard**: `5555 5555 5555 4444`
- **Amex**: `3782 822463 10005`

### Failed Payments:
- **Declined**: `4000 0000 0000 0002`
- **Insufficient Funds**: `4000 0000 0000 9995`
- **Expired Card**: `4000 0000 0000 0069`

### Special Cases:
- **3D Secure Required**: `4000 0025 0000 3155`
- **Requires Authentication**: `4000 0027 6000 3184`

**For all cards:**
- Use any future expiration (e.g., 12/34)
- Use any 3-digit CVC (e.g., 123)
- Use any billing ZIP (e.g., 12345)

---

## 🔍 Verification Checklist

After testing, verify the following:

### In Your Application:
- [ ] Billing page loads without errors
- [ ] Current subscription tier is displayed
- [ ] Credit balance is shown
- [ ] Subscription plans are visible with prices
- [ ] Credit packs are visible with prices
- [ ] Clicking "Upgrade" creates a checkout session
- [ ] Clicking "Buy Now" creates a checkout session
- [ ] After payment, you're redirected back
- [ ] Credits are added to your account (with webhooks)

### In Stripe Dashboard:
- [ ] Navigate to https://dashboard.stripe.com
- [ ] Go to **Payments** - verify test payment appears
- [ ] Go to **Customers** - verify customer was created
- [ ] Go to **Products** - verify all 7 products exist
- [ ] Go to **Subscriptions** (if you tested subscription)
- [ ] Check **Events** for webhook events

---

## 🐛 Troubleshooting

### Issue: "Payment processing is not enabled"
**Solution**:
- Check that `stripe` is installed: `pip install stripe`
- Restart the Flask application

### Issue: Checkout button does nothing
**Solution**:
- Open browser console (F12)
- Look for JavaScript errors
- Check that Flask app is running
- Verify API endpoint is accessible

### Issue: Redirected but no credits added
**Solution**:
- This means webhooks are not configured
- Set up Stripe CLI webhook forwarding
- Add webhook secret to `.env`
- Restart Flask application

### Issue: "Invalid price ID" error
**Solution**:
- Verify Price IDs in `config/.env` match what was created
- Check output from `create_products_auto.py`
- Ensure all price IDs start with `price_`

### Issue: Payment succeeds but nothing happens
**Solution**:
- Check Flask application logs for errors
- Verify webhook endpoint is accessible
- Check Stripe CLI is forwarding events
- Look for errors in Stripe Dashboard Events

---

## 📱 API Endpoints to Test

You can also test the API directly:

### Get Subscription Info:
```bash
curl http://localhost:5000/api/subscription
```

### Get Credit Packs:
```bash
curl http://localhost:5000/api/credits/packs
```

### Health Check:
```bash
curl http://localhost:5000/health
```

---

## 🎯 Complete Testing Flow

Here's a complete test scenario:

1. **Start Application** ✓ (Already running)
2. **Set up Stripe CLI** (in separate terminal):
   ```bash
   stripe listen --forward-to localhost:5000/api/stripe/webhook
   ```
3. **Open Browser**: http://localhost:5000/billing
4. **Check Initial State**:
   - Note your current credits (should be 200)
5. **Test Credit Pack Purchase**:
   - Click "Buy Now" on 100 Credits pack
   - Complete checkout with `4242 4242 4242 4242`
   - Verify redirect back to billing page
   - Verify credits increased to 300 (200 + 100)
6. **Check Stripe Dashboard**:
   - Verify payment appears
   - Check customer was created
7. **Check Webhook Events**:
   - Look at Stripe CLI output
   - Should see `checkout.session.completed`
8. **Check Application Logs**:
   - Look for "Credit pack (100) purchased"

---

## 🛑 Stopping the Application

When you're done testing:

1. In the terminal running Flask, press `Ctrl+C`
2. If you started Stripe CLI, press `Ctrl+C` in that terminal too

---

## 📊 Monitoring Tools

### Application Logs:
Watch the terminal where `python app.py` is running

### Stripe Dashboard:
https://dashboard.stripe.com
- **Payments**: See all transactions
- **Events**: See webhook events
- **Logs**: See API requests
- **Developers > Webhooks**: See webhook attempts

### Browser DevTools:
Press F12 in browser
- **Console**: JavaScript errors
- **Network**: API requests
- **Application**: Cookies/storage

---

## ✅ Success Criteria

Your integration is working correctly if:
- [x] Products created in Stripe ✓
- [x] Application started successfully ✓
- [ ] Billing page loads in browser
- [ ] Can create checkout session
- [ ] Can complete test payment
- [ ] Webhooks receive events (if configured)
- [ ] Credits update after payment (with webhooks)

---

## 🎉 You're Ready!

**Your Stripe integration is fully configured and ready to test!**

Open your browser now and go to: **http://localhost:5000/billing**

**Current Status:**
- ✅ Stripe products created
- ✅ Price IDs configured
- ✅ Application running on port 5000
- ✅ Ready to accept payments

**⚠️ Remember:** You're using **LIVE** Stripe keys, so test payments will be real. Consider switching to test keys for safe testing!

---

Need help? Check the application logs or Stripe Dashboard for details!
