# TODOS

Tracked from CEO plan review — 2026-03-15.

---

## P1 — Must fix before public launch

### [ ] Sentry error tracking
**What:** Integrate `sentry-sdk[flask]` to capture all unhandled exceptions in production.
**Why:** 94 broad `except Exception` handlers swallow errors silently. Production failures go undetected until users complain.
**How to start:** `pip install sentry-sdk[flask]`, add `sentry_sdk.init(dsn=os.getenv('SENTRY_DSN'))` before `app = Flask(...)`, set `SENTRY_DSN` env var.
**Effort:** S | **Depends on:** Nothing

### [ ] Log rotation
**What:** Cap `logs/agent.log` at 50MB with 5 rotations using `RotatingFileHandler`.
**Why:** Log file is already 19MB after 4 months. On a small VPS this will fill disk and crash the app.
**How to start:** Replace `FileHandler` with `logging.handlers.RotatingFileHandler(maxBytes=50*1024*1024, backupCount=5)` in logging config.
**Effort:** S | **Depends on:** Nothing

---

## P2 — Fix before paying customers

### [ ] Per-tier chat rate limiting
**What:** Apply tier-aware `@limiter.limit()` to `/api/chat` and `/api/chat/stream`.
**Suggested limits:** free: 10/hour, starter: 60/hour, pro: 200/hour, business: unlimited.
**Why:** Free-tier users can spam chat as fast as the server allows. Credit system helps but doesn't prevent burst abuse.
**How to start:** `limiter.limit(get_tier_limit)(chat)` — use a callable limit that reads `current_user.subscription.tier`.
**Effort:** S | **Depends on:** Nothing

### [ ] Streaming in-flight guard
**What:** Track a per-conversation `is_streaming` boolean flag; reject new messages while True.
**Why:** Double-click or rapid resubmit creates two concurrent AI streams on the same conversation — corrupts context and burns 2× credits.
**How to start:** Add `is_streaming = db.Column(db.Boolean, default=False)` to `Conversation` model. Set True at stream start, False on completion/error. Return 409 if True when new message arrives.
**Effort:** S | **Depends on:** Alembic (for migration)

### [ ] Dashboard sync async (30s page loads)
**What:** Move cloud resource sync from synchronous request handler to Celery task with progress polling.
**Why:** `infrastructure_sync.py` makes 10+ serial AWS API calls synchronously. A large AWS account causes 30+ second page loads or timeouts.
**How to start:** Create a `sync_cloud_resources.delay(user_id)` Celery task. Return task_id immediately. Frontend polls `/api/sync/status/<task_id>`.
**Effort:** M | **Depends on:** Redis/Celery already wired

---

## P3 — Architecture improvements

### [ ] Extract CreditService
**What:** Create `services/credit_service.py` that wraps all reads/writes of `credits_remaining`.
**Why:** Credits are accessed in 30+ places across app.py, routes, and services. Per-tool pricing or team credit pools would require touching all 30 places.
**How to start:** Create `CreditService.deduct(user, amount, reason)`, `CreditService.grant(user, amount, reason)`, `CreditService.balance(user)`. Replace usages gradually.
**Effort:** M | **Depends on:** Green test suite (to catch regressions)

### [ ] Fix `json.JSONDecodeError` and `BrokenPipeError` catches in chat stream
**What:** Explicitly catch `json.JSONDecodeError` from malformed AI responses and `BrokenPipeError` from dropped SSE connections.
**Why:** These fall through to broad `except Exception` — `BrokenPipeError` causes log noise; `JSONDecodeError` leaves the client with a broken stream and no error message.
**Effort:** S | **Depends on:** Nothing

### [ ] Extract `_ensure_subscription()` helper
**What:** Create a shared `_ensure_subscription(user)` helper in `routes/billing.py` that ensures a free `UserSubscription` row exists for a user, returning it.
**Why:** The same "get-or-create free subscription" block is copy-pasted in 3 places across `billing.py` (in `stripe_webhook`, `billing_success`, and `handle_checkout_completed`). Any change to free-tier seeding logic must be applied in all 3 places.
**How to start:** Extract the block into a function, replace all 3 call sites. Covered by existing `test_billing.py` suite.
**Effort:** S | **Depends on:** Nothing

### [ ] Move credit pack prices to config/DB (hardcoded USD price drift)
**What:** Replace hardcoded credit pack USD prices in `get_credit_packs()` and `get_billing_prices()` in `routes/billing.py` with values read from `NGNPriceConfig` or a new `CreditPackConfig` table.
**Why:** Pack prices ($10/$20/$35/$60) are currently hardcoded in two places inside the billing route. If prices change in Stripe, the billing page will show wrong amounts until code is manually updated.
**How to start:** Add a `usd_price` column to `NGNPriceConfig` (already has `price_ngn`), seed it from the existing price constants, and read from DB in both helper functions.
**Effort:** S | **Depends on:** DB migration
