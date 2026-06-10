# TODOS

Tracked from CEO plan review — 2026-03-15. Updated 2026-03-24 (EXPANSION mode review). Last updated 2026-06-10 (no-bs project analysis).

---

## P0 — From 2026-06-10 project analysis (in priority order)

### [ ] 1. Verify and complete API key rotation from April security incident
April's post-hack scan flagged all API keys for rotation (manual). Confirm it happened: check age/last-changed of AWS IAM keys, Anthropic, Moonshot, Groq, Stripe, Brevo, Sentry, SECRET_KEY, CREDENTIAL_ENCRYPTION_KEY (rotating this one requires re-encrypting stored user credentials). Sources: AWS Secrets Manager `devops-agent/production`, `.env`, GitHub secrets. Rotate anything pre-dating the incident.

### [ ] 2. Customer acquisition — first 20 paying users
Distribution, not code, is the gap. Execute MARKETING_PLAN.md + March Brevo campaign: launch email to contact list, Product Hunt / HN / r/devops posts, daily outreach, pricing page review. **Feature freeze until 20 paying users.**

### [ ] 3. Trust/social proof to overcome the credential barrier
Biggest conversion blocker: handing an unknown vendor cloud credentials. Build a public `/security` page (encryption, role-ARN mode, guardrails stack), promote "start in sandbox — no credentials needed" onboarding, publish auditable least-privilege IAM policy JSON for role-ARN setup.

**Role ARN over access keys (expanded):** Access-key mode means storing long-lived secrets that can do anything the IAM user can until manually rotated — the same failure mode as the April incident. Role ARN + External ID (the Datadog/Vanta model) means the customer creates a role in their own account that trusts ours, scoped by External ID against confused-deputy attacks; `get_user_boto_client()` already does STS AssumeRole with 1-hour temp creds, and the customer can revoke instantly by deleting the role. Code support exists (`credential_service.py` dual-mode) — the work is:
- [x] Make role-ARN the recommended/default option in the settings UI and onboarding (access keys demoted to "simple/self-hosted" fallback) — DONE 2026-06-10: settings toggle reordered + role-ARN default with trust-policy JSON shown; onboarding AWS panel got an IAM Role/Access Keys toggle (role default) wired to `/api/aws/config`; platform account ID exposed via `PLATFORM_AWS_ACCOUNT_ID` env (default 188046727805)
- [x] Write and publish the least-privilege IAM policy JSON customers can audit before connecting — DONE 2026-06-10: `static/iam/devops-agent-readonly.json` (metadata only — no s3:GetObject, no GetSecretValue, no ssm:GetParameter) + `static/iam/devops-agent-management.json` (full capability, IAM read-only, PassRole conditioned to AWS services, secret values still excluded); explained in `docs/iam-policies.md`, linked from settings + onboarding, guarded by `tests/test_iam_policies.py` (8 tests)
- [x] CloudFormation quick-create link that provisions role + policy + external ID in two clicks — DONE 2026-06-10: `cloudformation/devops-agent-role.json` generated from the policy files by `scripts/build_cf_template.py`, hosted at s3://devopsagent-cf-templates (public read, validated via CloudFormation API); "Create role with CloudFormation" buttons in settings + onboarding auto-generate an External ID and open the console quick-create page; drift guarded by tests
- [ ] Feature "we never need your access keys" on the `/security` page as a trust selling point
- [ ] Related (ties into P0 #1): switch our own CI (`ci.yml`/`deploy.yml`) from stored `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` GitHub secrets to GitHub OIDC → AssumeRole, eliminating long-lived keys

### [ ] 4. Decompose app.py (5,904 lines, 123 routes) into blueprints
Move route clusters into `routes/` blueprints group by group (chat APIs, dashboard, settings, onboarding, model switching). app.py becomes app factory + registration. Run pytest after each cluster. Target: under ~1,500 lines.

### [ ] 5. Tool reliability — smoke-test the 745-tool surface
(1) Registration integrity test: valid schemas, handler signatures match, every `delete_*`/`terminate_*` classified high-risk. (2) Live smoke test of ~30 most-used read-only tools against the real AWS account. (3) Error-path test: handlers return `{'success': False}` instead of raising.

### [x] 0. Root directory cleanup — DONE 2026-06-10
115 → 59 root entries. Junk scripts/screenshots deleted, contacts.csv untracked + purged from git history on both remotes, blog drafts moved to docs/blog/, stale remote branches deleted.

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

### [x] Add swarm activation logging — DONE (commit 5dea5b5)
`src/agent/core.py:1124`: `self.logger.info(f"Swarm: {effective_swarm} agents | score={swarm_score} | tier={swarm_max_agents}")` — added after `_compute_swarm_agents()` call.

### [x] Swarm metadata badge on message (🐝 N agents · Xs) — DONE
`templates/index.html`: strips `🐝 *Swarm active — N agents*` header from response text, appends `<div class="swarm-meta">🐝 N agents · Xs</div>` below the bubble using `Date.now()` delta from fetch start.

### [x] Auto-suggest swarm tip for follow-up queries — DONE
`templates/index.html`: tracks `_lastSwarmAgents`/`_lastSwarmElapsedSec` after each Kimi response. On next `oninput`, `_maybeShowSwarmTip()` inserts a dismissible `🐝 Tip: Add "across all regions"...` banner above the input if previous response took >30s with swarm active.

---

## P3 — Architecture improvements

### [x] Extract CreditService
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
