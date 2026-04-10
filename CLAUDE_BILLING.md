# DevOps Agent - Billing & Payments

> Complete billing system documentation.\n> See CLAUDE.md for architecture overview.

## Architecture

- **Frontend:** `templates/billing.html` — subscription tiers + credit pack purchase buttons, dual USD/NGN currency toggle
- **Stripe:** `stripe_integration.py` — `StripePaymentService` handles session creation for both USD and NGN
- **Currency detection:** `services/currency_detection.py` — IP geolocation + Accept-Language + user preference
- **Webhooks:** `/api/stripe/webhook` in `app.py`
- **Models:** `UserSubscription`, `CreditPurchase`, `SubscriptionTier`, `StripeWebhookEvent`, `PaymentWebhookEvent`, `NGNPriceConfig` in `models.py`

## Payment Flow (Stripe)

1. User clicks upgrade/purchase (currency toggle selects USD or NGN)
2. JS calls `/api/subscription/create-checkout` or `/api/credits/create-checkout` with `{currency: 'USD'|'NGN'}`
3. Backend creates Stripe Checkout session with `user_id` in metadata
4. For subscriptions, `subscription_data={'metadata': ...}` ensures metadata propagates to the Stripe Subscription object
5. User redirected to Stripe's hosted payment page
6. After payment, Stripe sends `checkout.session.completed` webhook
7. `handle_checkout_completed()` finds user by `metadata.user_id` (primary) or `customer_email` (fallback)
8. Saves `stripe_customer_id` and `stripe_subscription_id` on `UserSubscription` — required for all future recurring billing webhooks
9. Grants subscription tier + monthly credits (or adds credit pack credits)
10. User redirected to `/billing/success` — processes checkout inline as safety net if webhook hasn't fired yet
11. Billing page shows success toast and updated subscription data

## Webhook Event Handlers

| Event | Handler | Lookup |
|-------|---------|--------|
| `checkout.session.completed` | `handle_checkout_completed()` | `metadata.user_id` → `customer_email` |
| `invoice.payment_succeeded` | `handle_invoice_payment_succeeded()` | `stripe_customer_id` → `stripe_subscription_id` |
| `invoice.payment_failed` | `handle_invoice_payment_failed()` | `stripe_customer_id` → `stripe_subscription_id` |
| `customer.subscription.updated` | `handle_customer_subscription_updated()` | `stripe_subscription_id` |
| `customer.subscription.deleted` | `handle_subscription_deleted()` | `stripe_subscription_id` |

## NGN Prices (purchasing power adjusted)

| Product | USD | NGN |
|---------|-----|-----|
| Starter | $29/mo | NGN 15,000/mo |
| Professional | $99/mo | NGN 45,000/mo |
| Business | $299/mo | NGN 120,000/mo |
| 100 credits | $10 | NGN 5,000 |
| 250 credits | $20 | NGN 9,000 |
| 500 credits | $35 | NGN 15,000 |
| 1000 credits | $60 | NGN 25,000 |

NGN prices stored in `NGNPriceConfig` table. Each row has a `stripe_price_id_ngn` column for the corresponding Stripe Price ID in NGN currency.

## Security Requirements

- `/api/subscription/upgrade` — DISABLED (returns 403). Legacy endpoint that granted free subscriptions.
- `/api/credits/purchase` — DISABLED (returns 403). Legacy endpoint that granted free credits.
- Credits/subscriptions MUST only be granted via webhook handlers after Stripe verification.
- All webhooks use `PaymentWebhookEvent` for idempotency (format: `{gateway}:{event_id}`).

## Stripe Environment Variables

- `STRIPE_SECRET_KEY` — Stripe API secret key
- `STRIPE_PUBLISHABLE_KEY` — Stripe publishable key
- `STRIPE_WEBHOOK_SECRET` — Webhook signature verification secret
- `STRIPE_PRICE_STARTER` — Stripe Price ID for Starter tier ($29/mo USD)
- `STRIPE_PRICE_PROFESSIONAL` — Stripe Price ID for Professional tier ($99/mo USD)
- `STRIPE_PRICE_BUSINESS` — Stripe Price ID for Business tier ($299/mo USD)
- `STRIPE_PRICE_PACK_100` — Price ID for 100-credit pack ($10 USD)
- `STRIPE_PRICE_PACK_250` — Price ID for 250-credit pack ($20 USD)
- `STRIPE_PRICE_PACK_500` — Price ID for 500-credit pack ($35 USD)
- `STRIPE_PRICE_PACK_1000` — Price ID for 1000-credit pack ($60 USD)

NGN Stripe Price IDs are stored in `NGNPriceConfig.stripe_price_id_ngn` (database, not env vars).

## Setup Scripts

```bash
python scripts/seed_ngn_prices.py              # Seed NGNPriceConfig table
python scripts/create_stripe_ngn_prices.py     # Create Stripe Price objects for NGN products
```
