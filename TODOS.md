# TODOS

Tracked from CEO plan review — 2026-03-15. Updated 2026-03-24 (EXPANSION mode review). Last updated 2026-03-25 (implementation session).

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

### [x] Publish DevOps Agent as MCP server — DONE
`routes/mcp.py`: Flask blueprint at `/mcp` prefix. `GET /mcp/sse` — SSE stream with session registry (in-memory queue per session, 10min TTL). `POST /mcp/messages?sessionId=` — JSON-RPC 2.0 dispatch. Handlers: `initialize`, `tools/list` (returns all 258 tools in MCP `inputSchema` format), `tools/call` (runs handler with user context + safety check), `ping`. Auth: `Authorization: Bearer <api-key>` via `APIGatewayService`. Registered in `app.py` with `csrf.exempt(mcp_bp)`.

---

## P2 — Swarm observability (from CEO plan review 2026-05-11)

### [ ] Add swarm activation logging
**What:** Add `logger.info(f"Swarm: {effective_swarm} agents | score={score} | tier={tier}")` in `_call_kimi_api()` before the iteration loop.
**Why:** The scorer was recalibrated once already via Playwright testing — structured log data would make future recalibration a 5-minute log analysis instead of a multi-session Playwright debugging cycle. Currently swarm activations are invisible in server logs.
**How to start:** In `src/agent/core.py`, right after `effective_swarm = _compute_swarm_agents(...)`, add the log line. Expose `score` from `_compute_swarm_agents` (or duplicate the scoring inline for logging).
**Effort:** S | **Priority:** P2 | **Depends on:** Nothing

### [ ] Swarm metadata badge on message (🐝 N agents · Xs)
**What:** Each Kimi response bubble shows `🐝 5 agents · 42s` below the text. Agent count comes from the status header already emitted. Timing from JS-side `Date.now()` delta.
**Why:** Users wonder why some Kimi responses take 60s and others take 5s. The badge makes swarm timing visible and builds trust.
**How to start:** Parse the `🐝 *Swarm active — N agents*` line in the JS `formatMessage()` function, extract N, calculate elapsed time from when the fetch started, render a small `<span class="swarm-meta">` below the message bubble.
**Effort:** S | **Priority:** P3 | **Depends on:** Nothing

### [ ] Auto-suggest swarm tip for follow-up queries
**What:** If the user's previous query took >30s (swarm was active), show a hint in the input bar: `🐝 Tip: Add 'across all regions' to activate parallel scanning.`
**Why:** Discovery mechanism — most users don't know swarm exists or how to trigger it. This surfaces it contextually.
**How to start:** Track `lastRequestUsedSwarm` and `lastRequestMs` in JS. On next `keydown` in the input, show a dismissible tooltip if both conditions are met.
**Effort:** S | **Priority:** P3 | **Depends on:** Nothing

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

### [x] Move credit pack prices to config/DB — DONE (already implemented)
`models.py`: `NGNPriceConfig` already has `price_usd = db.Column(db.Numeric(10,2))`. `routes/billing.py` already reads `cfg.price_usd` with USD hardcode fallbacks. No additional work needed.

---

## Curriculum / Quiz

### [x] Cache Claude-generated quiz questions per module — DONE
`routes/curriculum.py`: `_quiz_cache: dict[str, tuple[list, float]]` at module level. `api_quiz_generate` checks cache first (TTL 1h); serves from cache if fresh, calls Claude on miss and populates cache. Questions are per-module (shared across users).

### [x] Auto-mark module complete on quiz pass — DONE
`routes/curriculum.py` `api_quiz_submit`: after `db.session.commit()`, if `passed` (pct ≥ 70): upserts `UserCurriculumProgress(completed=True, completed_at=datetime.utcnow())` for the module.
