# TODOS

Tracked from CEO plan review — 2026-03-15. Updated 2026-03-24 (EXPANSION mode review).

---

## P1 — Must fix before public launch

### [ ] Wire scheduler to autonomous services (THE BIGGEST PRODUCT GAP)
**What:** Connect `services/scheduler.py` to `ProactiveMonitoringService` and `IncidentResponseService`. Currently the scheduler runs every 30s but only reads DB rows and logs — it never calls cloud APIs or takes action.
**Why:** The autonomous AI SRE pitch requires the system to *act* without user input. CloudWatch monitoring (828 lines), incident playbooks (1,522 lines), and cost anomaly detection are all built and working. They're just not wired to the scheduler loop.
**How to start:** (1) Add file-lock guard so only 1 gunicorn worker runs the scheduler. (2) Add `_run_monitoring_tick()` that calls `ProactiveMonitoringService.check_all_users()` every 60s. (3) Add `_run_infra_sync()` that actually calls `InfrastructureSync.sync_all_users()` instead of just logging. (4) Connect `ProactiveMonitoringService` alert fires → `IncidentResponseService.process_alert()`.
**Effort:** M | **Depends on:** Scheduler race condition fix (see below) | **Priority:** Build immediately after race fix

### [ ] Fix scheduler multi-worker race condition (prerequisite for above)
**What:** Under gunicorn with `--workers N`, each worker starts its own scheduler daemon thread → N duplicate CloudWatch queries per user per tick.
**Why:** Must be fixed before wiring scheduler to real cloud API calls or costs multiply by N.
**How to start:** Add a `SCHEDULER_LEADER` env var + write a PID file in a temp dir on startup; only start the scheduler thread if the PID file doesn't exist. Alternatively use a Postgres advisory lock: `SELECT pg_try_advisory_lock(42)` — only one worker gets the lock. The file-lock approach is simpler for now.
**Effort:** S | **Depends on:** Nothing | **Priority:** Fix this FIRST, then wire scheduler

### [ ] Stripe webhook atomicity — wrap commit in try/except + rollback + re-raise
**What:** `handle_checkout_completed()` in `app.py` has no DB transaction guard. If `db.session.commit()` fails mid-handler (DB connection drop, OOM), user's payment is recorded in Stripe but no subscription is granted.
**Why:** Stripe retries webhooks for 72h on non-2xx responses. If we re-raise the exception, Stripe retries and eventually succeeds. Currently we swallow the error and return 200, losing the retry opportunity.
**How to start:** Wrap the handler body in `try: ... except Exception: db.session.rollback(); raise` and remove the `except Exception: pass` catch. Return 500 on DB failure — Stripe will retry.
**Effort:** S | **Depends on:** Nothing | **Priority:** Fix before first paying customer

### [ ] Build guided onboarding flow — /onboarding route
**What:** A 3-step onboarding wizard: (1) "Connect your first cloud account" with pre-filled form for AWS/Azure/GCP, (2) "Running your first scan..." with real-time progress, (3) "Here's what we found" — automatic discovery results showing resources, cost waste, security issues.
**Why:** New users who haven't connected cloud credentials currently get a raw boto3 error when they type any cloud command. There is zero guidance. This churns every trial user before they see value. The first scan moment IS the activation event — the moment a user goes from "curious" to "I need this."
**How to start:** Create `routes/onboarding.py`. Redirect new users (first login, no credentials) to `/onboarding`. After credential save, trigger `InfrastructureSync.sync_user()` + cost check + security scan. Show results. Redirect to `/chat` with a pre-filled message: "Here's what I found in your AWS account..."
**Effort:** L | **Depends on:** Scheduler wiring (for real scan results) | **Priority:** Build immediately after scheduler wiring

### [ ] First scan moment — auto-discover on cloud account connect
**What:** When a user saves their first cloud credentials (in /settings or /onboarding), automatically trigger an infrastructure discovery scan and present the findings *before* the user types anything.
**Why:** This is the 10-star activation moment. "I found 3 EC2 instances, $47/mo in terminated-but-not-removed resources, and 1 security group open to 0.0.0.0/0" delivered within 30 seconds of connecting an account makes $29/mo feel like a bargain. This transforms the product from "assistant" to "autonomous agent" from the user's first minute.
**How to start:** Add a `post_save` signal to the credential save endpoint. Kick off a Celery task (or inline with a thread) that calls `list_ec2_instances`, `list_security_groups`, `list_rds_instances`, checks `CostOptimization` findings. Store as `InfrastructureResource` rows. Show a "Welcome scan complete" page with summary.
**Effort:** M | **Depends on:** Onboarding flow | **Priority:** Build as part of onboarding

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

### [ ] Weekly infrastructure digest email
**What:** Every Sunday, each active user with connected cloud accounts receives an email: "Your infra this week — 2 incidents auto-resolved, $340 cost savings identified, 0 critical security alerts. Infrastructure health: B+."
**Why:** Weekly emails with real data are the #1 retention tool for B2B SaaS. They keep the product top-of-mind even for users who don't log in every day. Each email is a proof point that the product is working autonomously.
**How to start:** Add a weekly cron task in `scheduler.py`. Query each user's `Incident`, `CostOptimization`, `SecurityFinding`, and `Alert` tables for the past 7 days. Use `email_service.send()` with a new HTML template. Include a "View dashboard" CTA link.
**Effort:** M | **Depends on:** Scheduler wiring (so data is real) | **Priority:** Build after scheduler wiring

### [ ] Infrastructure health score on dashboard
**What:** An A/B/C/D/F grade shown prominently on the dashboard, calculated from: open critical security findings (-20pts each), cost waste > $100 (-10pts), incidents in past 7 days (-5pts each), uptime events (+5pts each). Gamifies improvement.
**Why:** New users need an immediate answer to "is my infra healthy?" A letter grade is the fastest possible answer. It also gives users something to improve, increasing engagement and retention.
**How to start:** Create `services/health_score.py` with `calculate_health_score(user_id) -> dict` returning `{grade: 'B', score: 78, breakdown: {...}}`. Call it in the dashboard route. Display prominently.
**Effort:** S | **Depends on:** Real scan data (scheduler wiring) | **Priority:** Build after onboarding

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
