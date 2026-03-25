# TODOS

Tracked from CEO plan review — 2026-03-15. Updated 2026-03-24 (EXPANSION mode review). Last updated 2026-03-24 (implementation session).

---

## P1 — Must fix before public launch

### [x] Wire scheduler to autonomous services — DONE
`services/scheduler.py`: PID file lock prevents duplicate scheduler threads under gunicorn. Added `_run_monitoring_tick()` (every 60s) — calls `ProactiveMonitoringService.check_now(user_id)` for every active user with cloud credentials. `_run_infra_sync()` now calls `sync_user_infrastructure(user_id)` for stale users (was only logging). Per-user sync runs in isolated daemon threads.

### [x] Fix scheduler multi-worker race condition — DONE
`services/scheduler.py`: `_acquire_scheduler_lock()` writes a PID file at startup. If another gunicorn worker already holds the lock and its process is alive, the new worker skips `start_scheduler()` silently. Stale locks from crashed workers are automatically reclaimed.

### [x] Stripe webhook atomicity — already correct (no fix needed)
`routes/billing.py`: `handle_checkout_completed()` subscription and credit_pack paths already have `try: db.session.commit() except Exception: db.session.rollback(); raise`. Outer handler returns 500 (triggering Stripe retry). Verified 2026-03-24.

### [x] Build guided onboarding flow — DONE
`templates/onboarding.html`: 4-step wizard — Welcome → Connect cloud (AWS/Azure/GCP credential forms) → Scanning (animated progress + real scan) → Results (resources found, cost findings, security findings, pre-filled first message). `app.py /chat`: redirects new users with no cloud credentials to `/onboarding`. `/api/onboarding/scan` endpoint runs `sync_user_infrastructure()` + queries findings summary.

### [x] First scan moment — DONE (part of onboarding)
`app.py /api/onboarding/scan`: After credentials saved in onboarding wizard, calls `sync_user_infrastructure(user_id)`, queries `CostOptimization` and `SecurityFinding` counts, returns summary with resource count, monthly cost, potential savings, critical security findings. Wizard shows real numbers in Step 3 and generates a personalised first chat message.

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

## P2 — Build for retention and growth

### [x] Weekly infrastructure digest email — DONE
`services/scheduler.py`: `_run_weekly_digest()` fires every Sunday (168h interval, weekday guard). Queries each user's past-7-day incidents, resolved count, cost savings, critical security findings. Calls `calculate_health_score()` for the grade. Sends HTML email via `EmailService.send_email()`. `_build_digest_html()` renders a branded dark-mode email with grade, stats table, and "View Dashboard" CTA.

### [x] Infrastructure health score on dashboard — DONE
`services/health_score.py`: `calculate_health_score(user_id)` returns `{grade, score, color, breakdown, last_updated}`. Deducts: critical security (-20pts each, max 60), high security (-8pts, max 24), cost waste (-10 per $100, max 30), unresolved incidents (-5pts, max 20), critical alerts (-5pts, max 15). `GET /api/dashboard/health-score`. Dashboard rebuilt from "Coming Soon" placeholder to full real-time dashboard: health grade front-and-center, 4 metric cards, health breakdown panel, recent incidents, cost-by-service, quick actions.

### [ ] Publish DevOps Agent as MCP server
**What:** Expose the 258 DevOps Agent tools as an MCP (Model Context Protocol) server, installable in Claude Desktop and other MCP-compatible clients. Users add it once and can manage their infra from Claude.ai.
**Why:** Zero-friction distribution. Every Claude power user who visits the MCP marketplace is a potential customer. The existing `/v1/tools` + `/v1/execute` API is 80% of an MCP server — it just needs an MCP-compliant wrapper and a listing.
**How to start:** Read the MCP server spec. Create `mcp_server.py` that wraps existing tool handlers in MCP tool format. Tools authenticate via API key. Publish to MCP marketplace with "DevOps Agent — 258 cloud tools" listing.
**Effort:** M | **Depends on:** Developer API (done) | **Priority:** After core product is stable

---

## P3 — Architecture improvements

### [ ] Extract CreditService
**What:** Create `services/credit_service.py` that wraps all reads/writes of `credits_remaining`.
**Why:** Credits are accessed in 30+ places across app.py, routes, and services. Per-tool pricing or team credit pools would require touching all 30 places.
**How to start:** Create `CreditService.deduct(user, amount, reason)`, `CreditService.grant(user, amount, reason)`, `CreditService.balance(user)`. Replace usages gradually.
**Effort:** M | **Depends on:** Green test suite (to catch regressions)

### [x] Fix `json.JSONDecodeError` and `BrokenPipeError` catches in chat stream — DONE
`app.py` `generate()`: explicit `except _json.JSONDecodeError` clause added before `except Exception`. Logs the malformed response with user context and yields a clear client-facing error message. `BrokenPipeError` was already caught at the earlier disconnect clause.

### [x] Extract `_ensure_subscription()` helper — DONE
`routes/billing.py`: `_ensure_subscription(user_id, initial_credits, stripe_customer_id, payment_gateway)` added after `_get_ngn_price_id()`. Two call sites replaced: `billing()` route (get-or-create free sub on page load) and `handle_checkout_completed` credit_pack branch (seed free sub when user has no subscription at time of credit pack purchase).

### [ ] Move credit pack prices to config/DB (hardcoded USD price drift)
**What:** Replace hardcoded credit pack USD prices in `get_credit_packs()` and `get_billing_prices()` in `routes/billing.py` with values read from `NGNPriceConfig` or a new `CreditPackConfig` table.
**Why:** Pack prices ($10/$20/$35/$60) are currently hardcoded in two places inside the billing route. If prices change in Stripe, the billing page will show wrong amounts until code is manually updated.
**How to start:** Add a `usd_price` column to `NGNPriceConfig` (already has `price_ngn`), seed it from the existing price constants, and read from DB in both helper functions.
**Effort:** S | **Depends on:** DB migration

---

## Curriculum / Quiz

### [ ] Cache Claude-generated quiz questions per module
**What:** Cache generated quiz questions (1-hour TTL, per-module) using a simple in-process dict or Flask-Caching.
**Why:** Every quiz attempt currently generates fresh questions from Claude (~$0.003/call). Users see different questions each attempt, making it hard to track genuine skill improvement vs. question-set variance.
**How to start:** Add a module-level `_quiz_cache: dict[str, tuple[list, float]]` in `routes/curriculum.py`. In `api_quiz_generate`, check cache before calling Claude; populate cache on miss. TTL = `time.time() + 3600`.
**Trade-off:** Fresh questions each time could also be considered a feature (harder to memorize). Consider making TTL configurable or per-user vs. shared.
**Effort:** S | **Depends on:** Nothing

### [ ] Auto-mark module complete on quiz pass
**What:** When a user scores ≥70% on a quiz, automatically upsert `UserCurriculumProgress.completed = True` for that module.
**Why:** Quiz completion and module completion are currently disconnected. Passing the quiz should reflect as progress.
**How to start:** In `api_quiz_submit` (routes/curriculum.py), after `db.session.commit()` on the attempt, if `passed` is True: upsert a `UserCurriculumProgress` record with `completed=True` and `completed_at=datetime.utcnow()` (reuse the same upsert logic from `api_update_progress`).
**Trade-off:** Some users may want to study without the quiz marking their progress. Consider adding a user preference toggle.
**Effort:** S | **Depends on:** Nothing
