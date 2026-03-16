# TODOS

Tracked from CEO plan review — 2026-03-15.

---

## P1 — Must fix before public launch

### [x] Sentry error tracking — DONE
`app.py:74-89`: `sentry_sdk.init()` with `FlaskIntegration` + `SqlalchemyIntegration`, `traces_sample_rate=0.1`. Set `SENTRY_DSN` env var to enable.

### [x] Log rotation — DONE
`src/utils/logging.py:139-143`: `RotatingFileHandler` with configurable `max_size_mb` (default 100MB) and 5 backups.

---

## P2 — Fix before paying customers

### [x] Per-tier chat rate limiting — DONE
`app.py`: `_chat_rate_limit()` callable + `@limiter.limit(_chat_rate_limit, key_func=lambda: str(current_user.id))` on both `/api/chat` and `/api/chat/stream`. Limits: free 10/hr, starter 60/hr, professional 200/hr, business 1000/hr.

### [x] Streaming in-flight guard — DONE
`models.py`: `Conversation.is_streaming` column. `api_chat_stream` checks and sets it before commit; `generate()` clears it in success path and `finally` safety net covers all error paths.

### [x] Dashboard sync async — DONE
`tasks/cloud_tasks.sync_user_infrastructure_task`: full sync + cost explorer + notifications. Route returns `{task_id}` immediately. `GET /api/dashboard/sync/status/<task_id>` polls state. Frontend polls every 3s (60 attempts max).

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
