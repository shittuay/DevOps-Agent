# DevOps Agent - Runbook & Historical Fixes

> Historical bug fixes, resolved issues, and gotchas.\n> See CLAUDE.md for active development guidance.

This document archives fixed issues and their solutions for reference. Most issues here are already resolved in the codebase and documented in git history.

## Resolved Issues / Gotchas

| Issue | Solution |
|-------|----------|
| **Scheduled audit found `git_stash_apply` unclassified in safety.py, and cataloged a ChatOps fabricated-data smell (2026-08-13)** | Routine code-vulnerability/smell/duplication scan. Cross-referenced every registered tool name (743 across all 17 `src/tools/*_tools.py` modules) against `safety.py`'s `high_risk_tools`/`medium_risk_tools` sets and both auto-detection prefix lists — the same `<provider>_<verb>_<noun>`-shape check that previously caught the `pagerduty_update_incident`/`opsgenie_*` gap (2026-07-18 entry below) and the git-tools RCE batch (2026-07-27 entry). Found one gap: **`git_stash_apply`** (`src/tools/git_tools.py`) merges a stash into the working tree via `repo.git.stash('apply', ...)` — the same "mutates the working tree, can conflict/overwrite" risk class as its sibling `git_merge_branch`/`git_cherry_pick`/`git_stash_drop` (all medium-risk) — but was present in neither explicit set nor matched by any auto-detect prefix, so it silently defaulted to low risk with no confirmation prompt. Fixed by adding it to `medium_risk_tools`. Regression test: `tests/test_new_tools.py::TestSafetyClassifications::test_git_stash_apply_is_medium_risk`. Verified `scripts/check_security_invariants.py` still reports zero violations. **Cataloged, not fixed this pass — needs a human call on scope:** `services/chatops_service.py`'s `_cmd_metrics` and `_cmd_oncall` (reachable live via `/chatops/slack/commands`, `/chatops/teams/commands`, and `/chatops/api/test` — all gated by real Slack HMAC / Bot Framework JWT verification, so not literally public, but every authenticated command produces this) return **hardcoded literal text** ("CPU Utilization: 45% (avg)", "Error Rate: 0.05%", "P95 Latency: 120ms", on-call `@devops-team`/`@sre-team`) with comments reading `# In a real implementation, this would fetch from Prometheus/CloudWatch` / `# ...integrate with PagerDuty/OpsGenie` — the identical tell-pattern behind the drift-detection incident CLAUDE.md's "every feature runs against a real cloud account" rule was written for. This is a real integration gap, not a demo stub: `monitoring_tools.py` already has working Prometheus/Datadog/Grafana clients and `alerting_tools.py` already has working PagerDuty/OpsGenie clients. Sibling commands in the same file (`_cmd_status`, `_cmd_incidents`) do call real backing services (`get_incident_engine()`, `get_monitoring_service()`), so this isn't a case of the whole feature being fake — just these two handlers. **Not fixed here because ChatOps has no per-tenant scoping to begin with** (`SLACK_BOT_TOKEN`/`TEAMS_APP_ID` are single global env vars, no `SlackWorkspace`/org-mapping model exists) — it's architected as one ops bot for the whole deployed instance, not a per-customer feature, so wiring `_cmd_metrics`/`_cmd_oncall` to real data requires first deciding *which* Prometheus/Datadog endpoint and *which* PagerDuty/OpsGenie account a single-instance bot should query (env-var-configured platform-wide credentials, presumably — a product decision, not a mechanical fix). Worth prioritizing regardless: fabricated "Error Rate: 0.05%" text returned to an on-call engineer mid-incident is actively misleading, not merely incomplete. **Also still open from the 2026-08-12 audit** (unchanged, re-confirmed this pass): `services/sandbox.py`'s `run_sandboxed()`/`run_script_sandboxed()` duplicate ~40 lines of Docker subprocess/timeout/kill-container/cleanup control flow; `app.py` still has 8 inline `current_user.role != 'admin'` checks that could use the existing `admin_required` decorator (which also logs denied attempts). **Verified clean in this pass:** `_reject_flag_like` git argument-injection guard coverage (no new unguarded bare-positional git functions since the 2026-08-04 audit); no new `# For now`/`# In a real implementation`/hardcoded-resource-id tells outside already-cataloged files; `scripts/check_security_invariants.py`'s SSRF/timing-check invariants. **Lesson:** the tool-risk-classification gap keeps recurring one tool at a time because it's opt-in per name with no structural enforcement (same caveat CLAUDE.md already states) — worth eventually turning into an AST-level test similar to `check_security_invariants.py` that fails when a registered tool name matches a mutating verb (from a fixed list) at any position and isn't in either explicit set or an documented auto-detect prefix, rather than relying on a human re-deriving the same cross-reference each audit. |
| **Workflow runs died with "Unexpected end of JSON input" — the keep-alive commits a 200 before the body exists (FIXED 2026-08-13)** | The owner ran the "EC2 + Nginx Web Server Setup" workflow; it really launched the instance, then the chat showed a bare `Error: Unexpected end of JSON input`. Traced live: `/api/chat`'s keep-alive (see the 524 entry below) flushes a whitespace byte at 15s, which commits HTTP 200 and the headers to the browser **long before the JSON body exists**. Anything that then kills the worker leaves the client holding a 200 whose body is pure whitespace, and `await kimiResp.json()` throws `SyntaxError: Unexpected end of JSON input` straight into `sendMessage`'s generic outer catch. Two independent killers, one symptom: run `wf_exec=4` was cut at 210s by the **deploy restart** for PR #136 (`systemd: Stopping DevOps Agent Gunicorn` 02:02:41 → gunicorn's default 30s `--graceful-timeout` expired → busy worker SIGKILLed 02:03:12; nginx logged `POST /api/chat 200 83`, 83 bytes of keep-alive whitespace); run `wf_exec=3` was cut at **exactly 300s** by gunicorn's own `--timeout` (`[CRITICAL] WORKER TIMEOUT (pid:871196)` at 19:15:20, `200 19` = 19 keep-alives). Every finalization step lived *after* the agent call inside the streaming generator, so both kills discarded the whole turn: prod had the user message but **zero** `usage_logs` rows, no assistant message, no credit deducted, and `workflow_executions.id=4` stuck at `running` — while the EC2 instance the turn created was really there. **Fix:** (1) `CHAT_MAX_TURN_SECONDS` (default 840, env-overridable) bounds the keep-alive loop so the view always emits a parseable JSON body (`still_running: true`) instead of losing the race to gunicorn; (2) finalization moved out of the generator into `_finalize_turn()`, called by the worker thread, so the turn is recorded even when the response is already gone; (3) frontend reads the body as text and reports a real message on a truncated/unparseable body instead of leaking the JSON parser's error, and marks the workflow execution `failed`; (4) `--graceful-timeout 300` + `TimeoutStopSec=330` so a deploy drains in-flight turns instead of guillotining them. **Two latent bugs fell out of (2):** `agent.last_tools_used` and `agent.pending_download` are `threading.local()`-backed (`_greenlet_local_property`), so the request thread had been reading its own empty defaults ever since the 524 fix moved the agent call onto a thread — every `/api/chat` turn was logged as `action_type='agent_message'` with `tool_name=None` regardless of tools used, and generated keypair downloads were silently dropped. Both verified failing against the pre-fix code. Tests: 4 added to `tests/test_chat_keepalive.py`. **Lesson:** streaming a keep-alive converts "the request failed" into "the request succeeded and then stopped mid-body" — every consumer of such an endpoint needs a truncated-body branch, because HTTP status can no longer carry the failure. |
| **Removing the fake sample-import left no way to create a baseline at all (FIXED 2026-08-12)** | Immediately after the drift fix below, the owner pointed out there was now no option to bring in a baseline. Correct: deleting `/api/import/sample` and its button removed the *only* baseline-creating control in the UI. `POST /api/baselines` and `POST /api/import/terraform` existed as endpoints but had no interface, so the dashboard could only ever scan zero baselines and report "No baselines configured". Deleting the fabricated path was right; leaving no replacement was not. **Fix:** `capture_baselines_from_account()` snapshots the user's real EC2 / security groups / S3 / RDS (paginated) as baselines, exposed at `POST /drift/api/baselines/capture`, plus a Terraform-state import UI (paste or file) driving the endpoint that already existed. Dashboard now has "Capture from AWS" / "Import Terraform State" / "Run Drift Scan", and an empty-state panel explaining what a baseline is. **The subtle correctness trap:** capture and scan must produce byte-identical config shapes, or every captured baseline reports drift the moment it's created — the single-resource `_fetch_*` path and the list-based capture path were therefore refactored to share `_normalize_ec2_instance`/`_normalize_security_group`/`_normalize_rds_instance`, and `test_captured_baseline_scans_clean` (capture, then scan an unchanged account, assert zero drift) is the regression guard. Capture skips terminated instances and unreadable buckets rather than pinning a half-empty baseline, and fails closed with `DriftScanError` → 502 when no account is attached. **Lesson:** when you delete the only path that did something — even a fabricated one — you have removed a capability, not just bad code. Check what the UI can still do afterwards. |
| **Drift detection reported entirely fabricated infrastructure — including a critical security alert — against accounts that didn't contain it (FIXED 2026-08-12)** | Reported by the owner, who spotted a drift report listing an RDS instance when their AWS account has no database at all. **Neither side of the comparison ever touched AWS.** `DriftDetectionService._get_actual_state()` was scaffolding — `# In a real implementation, this would call AWS APIs / For now, return simulated data` — returning hardcoded dicts, and `routes/drift.py`'s `/api/import/sample` seeded fake baselines (`i-0abc123def456`, `sg-12345`, `my-app-data-bucket`, `production-database`). Every user got a byte-identical report. The `t3.small → t3.medium` change was the literal `'instance_type': 't3.medium',  # May have changed`; the **critical** "security group allows ingress from 0.0.0.0/0" was the literal `{'port': 443, 'cidr': '0.0.0.0/0'},  # Changed!`. There was **no `RDS_INSTANCE` branch at all**, so RDS fell through to `return {}` — and `_compare_configs` reads an empty actual as "every expected property was removed", which is why one nonexistent database produced 6 separate findings. **Fix:** implemented real fetchers (`_fetch_ec2_instance`, `_fetch_security_group`, `_fetch_s3_bucket`, `_fetch_rds_instance`) reading through `credential_service.get_user_boto_client(user_id, …)` — the per-user path, never ambient app credentials — each returning `None` on a genuine not-found (AWS error codes `InvalidInstanceID.NotFound`, `InvalidGroup.NotFound`, `404`, `DBInstanceNotFound`; a `terminated` instance also counts as gone) so a missing resource yields one clean REMOVED finding instead of N phantom property removals. New `DriftScanError` aborts the scan when the account can't be read — **"cannot read the account" and "the account has drifted" are opposite conclusions, and conflating them is exactly how fictional findings shipped**; `/drift/api/scan` returns 502 with `scan_failed` rather than an empty/invented report. Deleted `/api/import/sample` and its dashboard button. **Three further bugs found while fixing this:** (1) `_compare_configs` reported every live property absent from the baseline as drift ("New property 'id' was added", remediation "Remove property 'id'" — impossible for an instance id); a baseline is a *subset* of pinned properties and real resources always carry more, so that loop was deleted. (2) It used `actual.get(key)` and treated `None` as "property removed", so a legitimately-null live value (an unencrypted bucket) was misreported; now uses a `_MISSING` sentinel. (3) `report.html` rendered `{{ drift.expected_value or 'N/A' }}`, so an expected `publicly_accessible: False` displayed as "N/A" — `False or 'N/A'` is `'N/A'` in Jinja; now `is none`. Also relabelled "Drift by Resource Type" → "Findings by Resource Type", since it counts `drift_items` (via `Counter`), not resources — 6 findings on one database read as 6 databases, which is what prompted the report. Tests: `tests/test_drift_uses_real_aws.py` (no credentials → raises rather than reports; missing RDS → exactly 1 REMOVED finding; live values actually surface; a locked-down SG produces no `0.0.0.0/0` alert; no hardcoded sample ids remain in source) plus `tests/drift_fakes.py`. Note baselines/reports are committed directly and outlive `db_session` rollback, so drift tests need explicit `clear_drift_state()` isolation. **Lesson → now a standing rule in CLAUDE.md ("every feature runs against a real cloud account"):** scaffolding that returns canned data is indistinguishable from a working feature until someone checks the account against it. |
| **Running a workflow did nothing — it appeared in Recent Chats, never in the chat window, and sat at "Running" forever (FIXED 2026-08-12)** | Three separate defects on the same path, all downstream of one wrong assumption: that writing a user `ChatMessage` row makes the agent run. It does not — **only `/api/chat/stream` runs the agent.** (1) `execute_workflow()` created a `Conversation` + a seeded user `ChatMessage` and returned `/chat?cid=X&wf_exec=N`. The row made the conversation appear in the sidebar, which is why it looked like something had happened. (2) **`templates/index.html` had no `cid` handler at all** — grepping it found `wf_exec` twice and `cid` zero times. The chat page renders whichever conversation `session['conversation_id']` points at, so it showed the user's *previous* chat while the workflow's conversation sat unopened. (3) The only code that marks an execution `completed` lives in the SSE `done` handler in the page, so with no stream ever starting, the row stayed at `running` permanently — "says running when it's not". **Fix:** stop pre-seeding the message. `execute_workflow` now creates an empty conversation, records the execution as `queued`, and returns the `prompt`; `workflows.html` stashes it in `sessionStorage` keyed by execution id; the chat page's new `cid` handler calls `loadConversation(cid)` (which already sets `session['conversation_id']` server-side *and* verifies ownership, so it binds the session as a side effect), marks the execution `running`, and sends the prompt through the normal `sendMessage()` path — reusing guardrails, credit accounting, streaming, and the status PATCH that all already worked. Keying the stash by execution id is what stops a later "View Chat" from re-running a finished workflow. Server-side, `list_executions` now reconciles rows stranded by a closed tab: past a 30-minute cutoff, an assistant reply in the conversation means `completed`, no reply means `timed_out` — status no longer depends on the browser reporting back. **Verified in a real browser** (local instance, Playwright), because unit tests cannot prove a UI dispatches anything: clicking Run Workflow put the prompt in the chat window with the agent streaming beneath it, the network log showed `execute` → `GET /api/conversations/<cid>` → PATCH `running` → PATCH `completed`, and the execution ended as `completed`. Revisiting the same URL fired **zero** stream/PATCH requests and just rendered the 2 stored messages. Tests: `tests/test_workflow_execute.py` (returns the prompt, persists no message, starts `queued`) and `tests/test_workflow_execution_status.py` (stale reconciliation; 3 of its 5 fail without the fix, the other 2 being the must-not-touch guards). **Lesson:** "the row is in the database" is not "the work is running". When a feature's completion signal is written only by client-side JS, the server has no idea whether it finished — give it a way to derive the truth itself. |
| **Import-time catalog seeding raced across gunicorn workers and double-seeded the catalog (FIXED 2026-08-12)** | Caught by verifying the workflow-seed fix below **on the live instance instead of trusting the deploy** — prod came back with 16 public workflows, not 8. Production runs 3 sync gunicorn workers; all 3 import `app.py`, and therefore run the import-time seeders, at the same moment. "Read existing names, insert the rest" is idempotent within one process but **not across processes**: each worker's read returned an empty set, so more than one inserted the whole catalog. The local end-to-end check couldn't have caught it — importing `app` twice *sequentially* against SQLite is exactly the case that works. **Fix:** `services/seed_lock.py`'s `seed_lock(key)` context manager wraps the check-then-insert in a Postgres transaction-level advisory lock (`pg_advisory_xact_lock`), which auto-releases on commit/rollback so a crashed worker can't strand it; it's a no-op on SQLite (single-process dev/tests). Applied to `seed_workflow_templates()` **and** to the pre-existing `seed_public_templates()`, which had the identical latent race — it happened to be clean in prod (1 row per name) only because it was seeded before a multi-worker restart, not because it was safe. Each catalog gets its own fixed lock key. Tests: `tests/test_workflow_seeding.py` asserts the advisory lock is actually issued (dialect faked to `postgresql`, `db.session.execute` spied) and that `seed_lock` rolls back on error rather than stranding the lock; a source-order check confirms the lock precedes the read, since a lock taken *after* the read would serialize nothing. **Lesson:** "idempotent" for a startup seeder means idempotent across concurrent processes, not just across restarts — and a local sequential re-import will never surface the difference. Anything that runs at import under gunicorn runs N times simultaneously, where N is the worker count. |
| **`/workflows` showed "No workflows in this category" for every category — the pre-built catalog was never seeded in prod (FIXED 2026-08-12)** | Reported from a screenshot: the "All" chip was active and the grid still rendered the empty state, with "No executions yet" below it. The page, the `/api/workflows` route, and the category filter were all correct — `workflow_templates` was simply an empty table. The 8 curated templates existed only as a `TEMPLATES` literal inside `scripts/seed_workflows.py`, a manual CLI script that nothing in the deploy path ever invokes, so the catalog was empty on every environment where someone hadn't run it by hand. **This is the identical bug `seed_public_templates()` already had** (see `app.py`'s import-time seeding block and its comment: "the `__main__` block never executes under WSGI, so the templates catalog stayed empty in prod") — a second catalog repeated it because the fix was applied to one catalog, not to the pattern. **Fix:** moved the data + an idempotent `seed_workflow_templates()` into `services/starter_workflows.py`, mirroring `services/starter_templates.py` + `seed_public_templates()`, and called it from the same import-time block in `app.py` (wrapped in try/except, non-fatal). The data could not stay in `scripts/` — that module does `from app import app, db`, so importing it from `app.py` would be circular. `scripts/seed_workflows.py` is now a thin CLI wrapper over the service function. **Verified end-to-end**, not just by unit test: imported `app` against a throwaway SQLite DB and confirmed 8 templates land with their steps intact, then re-imported against the same DB (restart simulation) and confirmed the count stayed at 8. Regression test: `tests/test_workflow_seeding.py` asserts the catalog seeds, is idempotent, is listable via `/api/workflows`, and that **every category chip hardcoded in `templates/workflows.html` matches at least one seeded workflow** — a chip with no matching category silently renders the same empty state. Note the test DB is shared across modules (`test_workflow_execute.py` leaves its own public template behind), so these assertions are scoped to the starter catalog by name rather than to absolute row counts. **Lesson:** a seed script under `scripts/` is not a deploy step. Any catalog that must be non-empty for a page to work needs idempotent seeding at import, and when you fix that for one catalog, grep for the others. |
| **Infrastructure map had no scrollbars — off-screen resources were reachable only by guessing you could drag (FIXED 2026-08-11)** | `templates/infrastructure/map.html`'s `#viewport` was `overflow:hidden` with `#world` absolutely positioned and moved by `transform: translate(tx,ty) scale(s)`. Nothing was ever scrollable: no scrollbars, no indication that content extended past the edge, and the `wheel` handler called `e.preventDefault()` unconditionally so even a wheel gesture zoomed instead of scrolling. The only way to reach an off-screen node was to know you could drag the background — undiscoverable, and impossible to judge how much map was left in either direction. **Fix:** moved to native scrolling. New structure is `#mapArea` (`flex:1`, non-scrolling frame) → `#viewport` (`overflow:auto`, the scroller) → `#canvas` (sizer whose box is the **scaled** content size — this is what gives the scrollbars their range) → `#world` (still unscaled coordinates, `transform: scale()` only, so all node-layout math is untouched). Pan now writes `scrollLeft`/`scrollTop`; `zoomAt(f, px, py)` rescales and then re-derives the scroll position so the content under the cursor stays put; plain wheel scrolls natively and ctrl/⌘+wheel zooms (also what a trackpad pinch sends). `viewOffset()` centers the map when the scaled content is smaller than the viewport, instead of leaving it jammed in the top-left. **Two non-obvious traps this hit:** (1) `#statsBar`/`#legend`/`#emptyState` were `position:absolute` children of `#viewport` — an absolutely-positioned child of a scrolling container scrolls with the content, so leaving them there would have made the legend and stats slide off screen; they had to become siblings of `#viewport` under `#mapArea`. (2) The dot-grid `::before` moved to `#mapArea` for the same reason, keeping it fixed as before. **Verified** in a standalone harness (template's `{% block main %}` + `theme.css` + 40 stubbed nodes, driven with Playwright): horizontal and vertical scrollbars appear exactly when `scrollWidth/Height > clientWidth/Height`, `canvas` box tracks `worldH × scale` exactly (1060 × 3 = 3180), a 120px drag moves scroll by exactly 120px, centering offset matches `(clientWidth − scaledWidth)/2`, and no console errors. **Lesson:** a transform-pan canvas gives up every affordance native scrolling provides for free — scrollbars as a position indicator, wheel/trackpad, keyboard paging, and the scrollbar as a drag target. Prefer a real scroll container with a sized element, and keep zoom as a transform on an inner layer. |
| **`business` tier was served the same model as `professional` at 3x the price (FIXED 2026-08-12)** | Flagged by the 2026-08-11 scheduled audit (PR #123), which correctly declined to decide it unilaterally; resolved by the repo owner as "business should be opus". `services/model_router.py` configured `business` as `claude-sonnet-4-6` in **both** `DEFAULT_TIER_MODELS` and `CLAUDE_OVERRIDE_CONFIGS`, identical to `professional`, while CLAUDE.md's Model Tier Mapping table advertised `claude-opus-4-6` for business ($299/mo vs professional's $99/mo). Business customers were paying 3x for an identical model. Nothing in the suite caught it: every existing assertion about the business tier covered `max_tools` and `trust_tool_results`, never `.model`. Fixed by setting both dicts to `claude-opus-4-6` / `Claude Opus 4.6`. Regression test added: `tests/test_tier_model_mapping.py` (6 tests) pins each paid tier to the model CLAUDE.md advertises, asserts business != professional, and asserts the default and override dicts agree with each other — the two-dict shape is what let the drift hide, since fixing one and not the other would silently change behavior depending on whether a user had ever touched the model toggle. Negative-tested: 3 of the 6 fail against the pre-fix config. **Not verified — the model id string itself.** `claude-opus-4-6` is taken from CLAUDE.md's table and matches the `claude-sonnet-4-6` convention that is known to work, but it could not be validated against the live API because **the Anthropic key does not authenticate in production** (see the next entry). If that string is wrong, business-tier requests will fail at the API rather than silently downgrade — validate it against `GET /v1/models` once a working key is in place. |
| **Anthropic API key returns 401 in production — professional AND business tiers cannot reach Claude (OPEN, found 2026-08-12)** | Found while trying to validate the `claude-opus-4-6` model id above. The key in the EC2 box's `/var/www/devops-agent/config/.env` is present (108 chars) but returns `HTTP 401 authentication_error` against `api.anthropic.com/v1/models`. The documented production path is supposed to bypass that file entirely — `init_secrets()` loads `MANAGED_SECRET_KEYS` from the `devops-agent/production` AWS secret when `FLASK_ENV=production` — but the instance role **cannot read Secrets Manager at all**: `get-secret-value` and `list-secrets` both fail from the box (`SECRET_UNREADABLE` / `LIST_DENIED`). So `secrets_are_authoritative()` is presumably False and the app falls back to the stale, invalid `.env` key. Net effect: every `professional` and `business` request routes to Anthropic (`services/model_router.py`), gets a 401, and `chat_service._is_anthropic_error()` sends it down the **Groq no-tools fallback** — so paying customers get "temporarily unavailable, generated without tool execution" instead of Claude with tools. This is the same failure shape as the Stripe stale-key incident, which is why `stripe_integration._ensure_stripe_configured()` now refuses the `.env` fallback in production; **the Anthropic path has no equivalent guard and fails silently into a degraded model instead of loudly.** Not fixed here — needs a valid key plus an IAM fix granting the instance role `secretsmanager:GetSecretValue` on `devops-agent/production`. Worth adding the same `secrets_are_authoritative()` gate to the Anthropic key so a stale key fails loudly rather than quietly downgrading paid tiers. |
| **AWS policy-freshness nudge was near-unreadable in light mode — amber-on-amber alert text (FIXED 2026-08-11)** | `templates/settings.html`'s `.alert-warning` (used only by `#awsPolicyNudge`, the "Your IAM role's policy is outdated" banner) set `color: var(--accent-warning, #ff6b35)` on a `rgba(255, 107, 53, 0.08)` background. In the light theme that renders amber `#fbbf24` text on a near-white pink wash — roughly 1.7:1 contrast, far under WCAG AA. Worse, `.alert-warning code` (the multi-line `aws cloudformation update-stack` command the user is meant to copy) used `background: rgba(0, 0, 0, 0.25)`, which over a light page is a mid-grey box still carrying inherited amber text — the command was effectively invisible. **Fix:** both rules now use `color: var(--text-primary)` and the code block uses `background: var(--bg-tertiary)` + `border: 1px solid var(--border-subtle)`. Those are the theme tokens from `static/css/theme.css`, so the text resolves to `#0f172a` in light mode and `#f8fafc` in dark — fixing light mode without inverting dark. **Lesson:** an accent color as an alert's *text* color only works when the alert background is dark. This codebase's alert palette (`.alert-success`/`.alert-error`/`.alert-info` all follow the same accent-on-10%-tint pattern) was written for the dark theme and inherited by the light theme unchanged; the other three have the same latent contrast issue and should move to `--text-primary` when touched. Colored borders/backgrounds are the right place to carry severity, not the body text. **Follow-up from the same audit:** `settings.html`'s `.alert-error` (line 276) and `.test-result.error` (line 412) both set `color: var(--accent-error)` — and **`--accent-error` is defined nowhere in the codebase**; the token in `static/css/theme.css` is `--accent-danger`. An undefined custom property is invalid at computed-value time, so `color` silently fell back to inherited body text and both rules rendered in ordinary text instead of red, despite each already carrying a matching `rgba(239, 68, 68, …)` background and border. Fixed by pointing both at `var(--accent-danger)`. A sweep of every `var(--accent-*)` reference under `templates/`+`static/` against `theme.css` found no other genuine dangling token (`--accent-slack`/`--accent-teams` resolve — they're defined locally in `templates/notifications/settings.html`). **Lesson:** a typo'd CSS custom property fails silently — no console warning, no visual error, just an inherited value that often looks plausible. There is no build step over these inline `<style>` blocks to catch it, so grep new `var(--*)` references against `theme.css` when touching a template's palette. |
| **`_get_gcp_client()` was dead code in every environment — one unsatisfiable import took down four working GCP services (FIXED 2026-08-11)** | Found while writing regression tests for the GCP credential-isolation fix (entry below). `_get_gcp_client()` opened with `from google.cloud import compute_v1, storage, container_v1, sql_v1, monitoring_v3` — but **`google-cloud-sql` does not exist on PyPI** (it sits commented out in `requirements.txt` with exactly that note), so that import raised `ImportError` on *every* call, for *every* `service_type`. `compute`, `storage`, `container` and `monitoring` are all installed and would have worked; they were taken down by the one unsatisfiable name sharing their import line. The function then compounded it by eagerly constructing **all five** clients and discarding four, so a request for `compute` also built storage/container/sql/monitoring clients. Net effect: all 8 non-SQL `_get_gcp_client()` call sites (`list_compute_instances`, `describe_compute_instance`, `list_storage_buckets`, `list_gke_clusters`, `get_cloud_monitoring_metrics`, and three others) returned "Google Cloud SDK not installed" no matter how the environment was provisioned — and the generic message made it look like a deployment problem rather than a nonexistent package. **Fix:** import and construct only the requested service's client, after the credential check; `sql` removed from the map entirely. **Cloud SQL** (the 3 functions that genuinely needed `sql_v1` — `list_cloud_sql_instances`, `delete_cloud_sql_instance`, `restart_cloud_sql_instance`) now goes through a new shared `_get_sqladmin_client()` helper using the REST discovery API (`googleapiclient.discovery.build('sqladmin', 'v1beta4', ...)`), which is a real pinned dependency (`google-api-python-client`) and was **already the pattern `create_cloud_sql_instance` used — which is why that one function was the only Cloud SQL tool that worked.** `create_cloud_sql_instance`'s inline copy was collapsed onto the shared helper. Credential resolution now happens *before* any SDK import, which is also what makes `_get_gcp_client` unit-testable at all — the previous version raised `ImportError` before reaching any credential logic, so the fail-closed behavior could not be tested on any platform. Regression tests added to `tests/test_gcp_credential_fail_closed.py` (now 9): fail-closed with an explicit `project_id`, single credential resolution per call, `_get_gcp_client('sql')` rejected, `_get_sqladmin_client()` fails closed, and an **AST-based guard that no live `sql_v1` import is ever reintroduced** (AST rather than text search specifically because the module's own comments discuss `sql_v1` by name to explain why it must not be imported — negative-tested by injecting a real import). Full suite: **696 passed, 1 skipped**. **Lesson:** a shared import line is a single point of failure for every symbol on it — one optional/nonexistent package silently disables every sibling service, and the resulting "SDK not installed" message points at the environment instead of the dependency list. Import per-service and lazily when the services are independent. |
| **Scheduled audit found execute_change privilege escalation — any org member could run another user's approved change (FIXED 2026-08-09)** | Routine code-vulnerability scan reviewing the diff since the 2026-08-06 audit found that `routes/changes.py`'s `execute_change()` (`@login_required` only, no `@approver_required`) authorized non-owners with `user_is_admin(current_user) or _change_visible_to_approver(change, current_user)`. `_change_visible_to_approver()` is a **pure org-membership check with no role gate** — every one of its other three call sites (`get_change`, `approve_change`, `reject_change`) pairs it with an explicit approver-or-admin role check first (either `@approver_required` on the route or an inline `user_role in ('approver', 'operator')` guard), but `execute_change` called it alone. Any plain `role='user'` member of the same organization as an already-approved change — not the requester, not an approver, just a teammate — could `POST /api/changes/<id>/execute` and have it actually run: `_execute_change()` performs the real action (including delete/terminate) via `get_user_boto_client(change.user_id, ...)`, i.e. the **change owner's own stored AWS credentials**, so this was live cloud impact, not just an API-authorization gap. Concrete scenario: Carol (role=`user`) requests "terminate production RDS `acme-prod-db`", Alice (role=`approver`) approves it, and Bob — a plain org-mate with no approver privilege and no involvement in the change — could execute it himself once approved. Fixed by requiring `user_is_approver(current_user)` in addition to the org-scope check in `execute_change`, matching the sibling routes; also reworded `_change_visible_to_approver`'s docstring (it previously read "whether a non-admin approver may view/act on this change," which is exactly the misleading implication that let the gap in — it performs no role check at all) to make explicit that callers must pair it with their own role gate. Regression test added: `tests/test_change_governance_org_scope.py::test_plain_org_member_cannot_execute_another_users_approved_change`. **Also checked in the same pass, no new issues found:** `services/ai_infrastructure.py`'s just-fixed `get_template()` public-or-owned filter (confirmed every call site constructs the service with a real `current_user.id`, so the `self.user_id is None` bypass path is unreachable — the standalone `get_ai_infrastructure_service()` factory that defaults to `user_id=None` is never called anywhere); SSRF via non-`requests` HTTP paths (only hit was the already-guarded `ssl.get_server_certificate` in `aws_tools.associate_eks_oidc_provider`); git flag-injection coverage across every `git_tools.py` function (all positional-argument call sites already guarded); `safety.py` risk classification against all 745 registered tools (no gaps). **Lesson:** this is the same structural gap CLAUDE.md's "two independent role systems" and SSRF/timing-check lessons describe — a shared helper that answers a narrower question than its name implies (`_change_visible_to_approver` only ever checked org membership, never role) will eventually get called somewhere without its usual paired guard; when reusing a shared scoping helper, verify what it actually asserts, not what its name suggests. |
| **Scheduled audit found a latent public-template delete IDOR, two silent safety-gate failures, and a security-scanner coverage gap (FIXED 2026-08-07)** | Routine code-vulnerability/smell/duplication scan (bandit static scan + two parallel research sweeps for silent exception-swallowing and duplicated logic, on top of manual review) found four issues, all fixed, plus several lower-severity items cataloged for a future pass. **(1) `services/ai_infrastructure.py`'s `delete_template()` reused `get_template()`'s read-permission check (`template.is_public or template.user_id == self.user_id`) as its delete-authorization check.** `is_public` is meant to grant *read* access to everyone (so `preview_template`/`api_template_clone` can render/clone public starter templates) — reusing the same predicate for delete meant any authenticated user could delete any *public* `InfrastructureTemplate`, not just their own. No route currently calls `.delete_template()` (confirmed via repo-wide search — `app.py`'s `/api/templates/<id>` DELETE route is a same-named-but-separate `CommandTemplate` feature with its own correct `user_id != current_user.id → 403` check, and is unaffected), so this was not live-exploitable today, but it's the same "getter fixed for read, forgotten for a stricter caller" shape as the `ComplianceService`/`view_team` postmortems above — fixed now, before a delete route gets wired up, by giving `delete_template()` its own strict ownership-only query instead of delegating to `get_template()`. **(2) Two safety-validator call sites fail open with zero log line.** `routes/mcp.py`'s MCP tool-execution path and `routes/api_gateway.py`'s `/v1/agent` both wrap `SafetyValidator().validate_tool_call()` in a bare `except Exception: pass`/`validation = None` — a deliberate, consistent design (matches the Haiku guardrail screen's documented fail-open behavior in CLAUDE.md), not a bug, but with zero logging a validator that started throwing on every call (bad deploy, DB hiccup, whatever) would silently disable confirmation gating for every high-risk tool call on both entry points indefinitely with no operational signal. Fixed by logging the exception at both sites before continuing — behavior unchanged, but now visible. **(3) `services/security_scanner.py`'s `scan_s3_buckets()` silently skipped the public-bucket-ACL and versioning checks on any API error** (`except Exception: pass`, no logging), so a permissions/throttling error on `get_bucket_acl` for one bucket looked identical to "checked it, not public" in the resulting compliance report — silently dropping a potential `critical`-severity `open_s3_bucket` finding with no indication the scan was incomplete. The sibling encryption check in the same function already surfaced API failures as a finding; ACL and versioning didn't. Fixed by adding `logger.warning()` on both (module had no logger at all — added one; also swapped the outer handler's bare `print()` for `logger.error()` for consistency). **Verified:** `scripts/check_security_invariants.py` clean; all four edited files pass `py_compile`; `bandit -r .` run for the first time in this repo (no prior audit had run it) surfaced 36 findings, all reviewed — the MD5/SHA1 hits are non-security cache-key hashing and the AWS-mandated EKS-OIDC-thumbprint algorithm (false positives), the `urllib.request.urlopen` hit is HIBP's hardcoded host with only the URL-encoded email path segment caller-influenced (not SSRF), and `scripts/restore_prod_locally.py`'s f-string SQL interpolates from a hardcoded table-name tuple in a local-only dev script (not attacker-reachable) — none required a fix. Full `pytest` run wasn't possible in this sandbox (`pip install -r requirements.txt` fails on an unrelated broken `multi-key-dict` wheel, and a minimal-dependency install hit a pre-existing `blinker`/debian-packaging conflict) — verification relied on the AST-based invariant scanner, `py_compile`, and manual call-chain tracing, same fallback prior sandbox-constrained audits used. **Cataloged, not fixed this pass:** `tools/remote-control/server.py` (a personal local dev utility, not part of the deployed Flask app or any CI/deploy path) binds `0.0.0.0:9090` with **zero authentication** and `Access-Control-Allow-Origin: *`, exposing a `POST /run/<action_id>` that shell-executes one of eight hardcoded commands (including `git pull origin main`, killing/restarting the local app, running the test suite) to anyone on the same LAN — and, because a same-origin-policy-exempt simple POST isn't blocked from *sending* (only from having its response read), to any website the developer's browser visits while the server is running (CSRF-style trigger). Left for the repo owner to decide the intended trust model (add a shared-secret token? bind to localhost + reverse-tunnel only?) rather than unilaterally changing a personal tool's behavior. Also cataloged: `app.py` has 8 call sites plus `routes/approvals.py`/`routes/changes.py` doing a literal `current_user.role == 'admin'` check instead of calling `services/rbac.py`'s `user_is_admin()` — behaviorally identical today (admin is top of the role hierarchy) but a landmine if a role above admin is ever added, the same "shared helper exists, N call sites don't use it" shape as the `user_active_org_ids()` lesson above; `services/cost_explorer.py` and `services/infrastructure_sync.py` each define a byte-identical `_get_user_boto_client()` wrapper around `credential_service.get_user_boto_client()` (trivially collapsible, currently harmless); `services/security_scanner.py`'s own `_get_boto_client()` has a different signature than `src/tools/aws_tools.py`'s and silently falls back to request-scoped user resolution when `user_id` is omitted — no current call site omits it, but a future scheduler/background call site that does would silently misbehave instead of failing loudly; `src/tools/aws_tools.py`'s `list_load_balancers`/`list_waf_web_acls` swallow per-API-call errors and still return `'success': True`, so a failed ELB/WAF listing looks identical to "none exist" (same shape as the S3 versioning/ACL gap just fixed, lower severity since these aren't compliance-critical findings). The multi-region `_all_regions` AWS tools (`list_ec2_all_regions` etc., via the shared `_parallel_region_scan` helper) were checked against the prior 2026-08-06 entry's suspicion that they silently drop regions — they don't: each already returns a per-region `errors: {region: msg}` dict to the caller, so that specific concern in the prior entry no longer applies (either already fixed or the prior entry described stale code). **Lesson:** the two safety-gate fail-opens (finding #2) are the same "consistent-by-design but silent" gap as the guardrails screen's own documented fail-open — worth treating "fails open, deliberately" as its own checklist item requiring a log line, not just a try/except, wherever it's introduced next. |
| **Dependabot's `cryptography` 48.0.1 → 50.0.0 bump broke `pip install` and turned `main` red, blocking every deploy for ~19h (FIXED 2026-08-06)** | PR #115 (`c385f4f`, merged 2026-08-06 03:27 UTC) bumped `cryptography` to `50.0.0` but left `pyopenssl==26.2.0`, which requires `cryptography<49`. Every CI run after that merge died in the `Run Tests` job at the install step with `ResolutionImpossible: pyopenssl 26.2.0 depends on cryptography<49 and >=46.0.0`. Because `test` is a required check for the `status-check` gate, `Deploy to EC2` was **skipped on every push to main** — production stayed pinned to `5bce326` (the last green run, 2026-08-03) while 7 merged PRs piled up undeployed, including the git RCE / container-escape / credential-isolation security batch (`ffe831a`) and the `/api/chat` Flask app-context fix (`56524a3`). Note the failure is silent from the app's perspective: `/api/status/health` stayed fully green the whole time because prod was serving healthy *stale* code. **Fix:** bump `pyopenssl` to `26.4.0` (requires `cryptography>=49,<51`), keeping `cryptography==50.0.0` — reverting to 48.0.1 was rejected because 50.0.0 carries **CVE-2026-69247**, a Bleichenbacher timing oracle in `pkcs7_decrypt_der`. The old pin comment claimed a `<49` "msal cap"; that was **stale** — `msal` 1.37.0 allows `cryptography<51,>=2.5`, so nothing else held the ceiling down. **Gotcha:** `pyopenssl` and `cryptography` must be bumped in lockstep; Dependabot only bumps the one it has an advisory for and cannot read the pin comment, so it will re-break this pairing on the next `cryptography` major. When a Dependabot PR's own CI is red, do not merge it — the red run at 00:13 on PR #115 predicted this exact failure. |
| **Scheduled audit found the 524-fix's background thread silently dropped the Flask app context, breaking every real tool call (FIXED 2026-08-05)** | Routine code-vulnerability scan reviewing the diff since the last audit (2026-07-27) found that `5e39d02`'s `/api/chat` keep-alive fix (see the Cloudflare 524 entry below) moved `agent.process_message_isolated(...)` into a plain `threading.Thread(target=_run_agent_call)` with no `app.app_context()` pushed inside it. A brand-new `threading.Thread` does not inherit the Flask request/app context from the thread that spawned it (contextvars aren't copied to a manually-started thread, and — confirmed live — production actually runs plain sync gunicorn workers, not the gevent config the Procfile describes, so there's no monkey-patched thread-local magic to paper over this either). `process_message_isolated` goes on to do real DB work from inside that thread on almost every substantive turn: `credential_service.py`'s `UserCloudCredential.query` (every AWS/Azure/GCP/K8s tool call that needs per-user credentials), `skills_engine.py`'s `UserSkillActivation`/infrastructure-summary queries, etc. — all of which raise `RuntimeError: Working outside of application context.` outside a pushed context. That exception was caught by `_run_agent_call`'s own `except Exception`, turning into a generic `"Error processing request: Working outside of application context...."` response — and `_is_anthropic_error()` could then trigger the Groq no-tools fallback, so the failure often surfaced only as "Claude/Kimi is temporarily unavailable, this response was generated without tool execution" rather than a visible crash. Net effect: since the Jul 30 deploy, most `/api/chat` (non-streaming) turns that actually needed a cloud tool call were silently losing tool execution in production. `/api/chat/stream`'s SSE path was unaffected — it calls `agent.process_message_streaming` directly inside the `stream_with_context`-wrapped generator on the *original* request thread, never spawning a separate thread. Fixed by wrapping `_run_agent_call`'s body in `with app.app_context():`. Regression test added: `tests/test_chat_keepalive.py::test_background_thread_has_app_context_for_db_access` — unlike the fix's original four tests (which fully mock `process_message_isolated` and never exercise this path), this one has the fake agent call perform a real `UsageLog.query` from inside the background thread; confirmed it reproduces the exact production error message before the fix and passes after. Full suite: 667 passed, 1 pre-existing unrelated failure (missing `ANTHROPIC_API_KEY` in the sandbox used to run the suite). **Verified clean in the same pass:** every other `threading.Thread(target=...)` call site in the codebase (`routes/auth.py`'s password-reset/signup-email dispatch, `services/notification_service.py`'s webhook dispatch, `services/proactive_monitoring.py`) already wraps its body in `app.app_context()` — this was an isolated regression introduced by the 524 fix, not a systemic pattern; the two other Jul 27–Aug 5 diffs (Azure friendly-error-message translation, the CI deploy-pin/concurrency-group fix) were reviewed and are clean. **Lesson:** "runs the agent call in a background thread" and "runs the agent call in a background thread that also participates in Flask/DB machinery" are different claims — a fix's own regression tests need at least one case where the mocked entry point does the kind of real work (DB/app-context-dependent) the code path exists to do, or a context-loss bug like this one sails through fully green. |
| **Scheduled audit found git argument-injection RCE + two org/user-isolation IDORs (FIXED 2026-07-27)** | Routine code-vulnerability scan (parallel sweeps of routes/services for IDOR, of src/tools for injection/SSRF gaps, and of known duplicated code) found three real issues. **(1) Git argument-injection → command execution, highest severity:** `src/tools/git_tools.py`'s `git_pull`/`git_push`/`git_force_push_branch`/`git_push_tag` passed caller-supplied `remote`/`branch`/`tag_name` as a bare positional argument to GitPython's `repo.git.<subcommand>(*args)` with no validation. GitPython invokes `git` directly with no shell (not the shell-injection class `scripts/check_security_invariants.py` tracks), but git itself treats a leading `-` as an option regardless of position, and `git pull`/`fetch --upload-pack=<cmd>`, `git push --receive-pack=<cmd>`, and `git rebase --exec=<cmd>` (found the same way in `git_rebase_branch`'s `onto_branch`) all execute `<cmd>` on the host as part of the transport/rebase machinery. A chat-driven caller could set `remote="--upload-pack=touch$IFS/tmp/pwned;true"` and reach command execution independent of the medium/high-risk confirmation gate on these tools (the prompt shows "pull from X", it doesn't recognize X as a flag). Fixed with a shared `_reject_flag_like(value, param_name)` helper (rejects any value starting with `-`) called before `_get_repo()` in every function passing a caller-supplied ref/remote/branch/commit/tag as a bare positional arg — the RCE-capable set above plus `git_switch_branch`, `git_delete_branch`, `git_merge_branch`, `git_rename_branch`, `git_reset_to_commit`, `git_cherry_pick`, `git_delete_tag`, `git_revert_commit` for defense-in-depth (no known RCE flag on those, but the same ambiguity of how each subcommand's parser treats a dash-prefixed positional). Regression tests: `tests/test_git_tools_argument_injection.py` (13 tests — confirms the guard fires *before* `_get_repo()` runs, and that normal values pass through untouched). **(2) `services/compliance_service.py` IDOR:** `get_policy()`/`get_compliance_report()` did a bare `Model.query.get(id)` with no `user_id` filter even though `ComplianceService` is always constructed with one — any logged-in user could toggle, delete, or download another user's compliance policy/report by guessing the integer id (`toggle_policy`/`delete_policy`/`update_policy`/`get_report`/`export_report` all call one of the two unfiltered getters). Fixed by filtering both on `self.user_id` when set. Regression tests: `tests/test_compliance_policy_idor.py` (5 tests). **(3) `routes/approvals.py` org-scope leak:** same bug class as the change-governance fix below, in a route file that was never given the same treatment — `get_pending()`/`get_count()`/`get_history()` are gated only by the platform-wide `_approver_required` (no org-membership check) and query `InfrastructureChange` — which carries `organization_id` specifically to scope non-admin approver visibility — with no org filter at all, leaking every organization's pending/historical change details (requester, resource, risk reason) to any platform-role approver. Fixed with a local `_org_scoped_change_query()` helper that reuses `routes.changes._user_active_org_ids()` rather than re-deriving the org-membership logic a third time. `ApprovalRequest` (the agent tool-call approval side of the same endpoints) has no `organization_id` and is intentionally platform-wide, so it was left untouched. Regression tests: `tests/test_approvals_org_scope.py` (3 tests). Full suite after the fixes: 630 passed (plus 21 new), 1 pre-existing unrelated failure (missing `ANTHROPIC_API_KEY` in the sandbox used to run the suite). **Also cataloged, not yet fixed (lower risk / larger diff, left for a future pass):** duplicated OpenAI-compatible `chat()`/`chat_stream()` logic across `services/model_failover.py`'s three provider classes; `create_or_update_recommendation()` defined twice, with diverged behavior, in `services/cost_explorer.py` and `services/infrastructure_sync.py`; near-identical `docker_compose_up`/`docker_compose_down` in `docker_tools.py`; three structurally-identical email-template functions in `services/email_service.py`; duplicated header-parsing block between `require_api_key`/`optional_api_key` in `services/api_key_service.py`. **Lesson:** the SSRF/shell-injection guard pattern doesn't cover every way a "safe because no shell" subprocess call can still be attacker-steerable — GitPython's argv-passthrough is real command execution once a positional argument can be flag-shaped; any future tool wrapping a CLI that accepts `--upload-pack`/`--receive-pack`/`--exec`-style transport/hook options needs the same bare-positional-argument scrutiny, not just a shell-metacharacter check. |
| **Scheduled audit found curriculum AI-guide guardrail bypass + three SSRF gaps (FIXED 2026-07-23)** | Routine code-vulnerability scan (guardrails / safety.py / SSRF / user-isolation sweeps) found: (1) `routes/curriculum.py`'s `/curriculum/api/ai-guide` streamed a free-text `question` straight into a Kimi chat completion with **none** of the four mandated guardrail steps (no `sanitize_input`, no `is_guardrail_blocked` check, no `validate_message`, no `screen_message`) — the same bug class as the `api_gateway.py`/`api/v1/conversations.py` incidents below, just not yet caught. Fixed by porting the same guardrail block (including crisis-language handling, logged to `CrisisIncident` with `conversation_id=f'curriculum:{module_id}'`) used in `app.py`'s `/api/chat`. (2) `services/notification_service.py`'s `SlackClient.send_webhook`/`TeamsClient.send` POST to a user-configured `webhook_url` (set via `routes/notifications.py`) with **zero** SSRF validation — pointing it at `http://169.254.169.254/latest/meta-data/` made the server fetch cloud metadata on every notification event, and the Slack path even logged the response body. Fixed by calling `assert_safe_url()` before both requests. (3) `services/api_gateway.py`'s `test_webhook()` skipped the `_is_safe_webhook_url()` guard that `trigger_webhook()` already had, and echoed up to 500 chars of the response body straight back to the caller — a direct SSRF response oracle for anyone who owns a webhook row. Fixed by adding the same guard used elsewhere in the file. (4) `src/tools/git_tools.py`'s `_validate_git_url()` only checked URL *shape* (scheme/pattern), never resolved the host — `git_clone_repository`/`git_add_remote` would let `git`'s own HTTP transport issue a real GET to `http://169.254.169.254/...` before failing. Fixed by resolving the host (both `https://` via `assert_safe_url()` and `git@host:` via direct `getaddrinfo` + the shared `_is_blocked_ip()` check) and rejecting loopback/link-local targets. **Verified clean in the same pass:** `safety.py` risk classification (all 745 tools cross-referenced, zero gaps), user-isolation/IDOR shape across all per-user models (zero unfixed instances), Datadog/PagerDuty/OpsGenie/Prometheus/Grafana/Jenkins/SonarQube/Nexus SSRF wiring. **Open item at the time, since fixed same day** (see the entry directly below): `routes/changes.py`'s `approve_change`/`reject_change` let any user holding the `approver` role act on *any* pending change regardless of who it's assigned to, while the sibling `list_pending_approvals` scopes non-admins to `user_id=current_user.id`. |
| **Change governance had no tenant boundary — any approver could act on every customer's changes (FIXED 2026-07-23)** | Flagged as an open item in the entry above, then investigated further same day: the gap was broader than an assignment mismatch. `InfrastructureChange` (`models.py`) only ever tracked `user_id` (requester) and `approver_id` — no assignment/team field existed. `routes/changes.py`'s `list_changes`, `approve_change`, `reject_change`, and `rollback_change` gated purely on the **platform-wide** `User.role` (`admin`/`approver`/`user`/`viewer`, only settable via direct DB edit — see "Granting Admin Access" in CLAUDE.md) and queried the entire `InfrastructureChange` table with zero org boundary: any account promoted to `role='approver'` could view, approve, reject, or roll back **every customer's** infrastructure changes platform-wide, not just their own team's — this is a different, unrelated role system from the per-org `OrganizationMember.role` (`owner`/`admin`/`member`) used in `organizations.py`, and the two never cross-checked each other. Separately, `list_pending_approvals` filtered non-admins to `user_id=current_user.id` — showing an approver only changes *they personally submitted*, never other users' changes awaiting approval — while the action endpoints had no such filter, so an approver could act on a change by ID that never appeared in their own pending list. Fixed by adding `InfrastructureChange.organization_id` (nullable FK, stamped at creation from the requester's `session['active_organization_id']`, validated against real `OrganizationMember` rows so a tampered session value can't assign a change to a foreign org) and scoping every non-admin approver path (`list_changes`, `get_change`, `list_pending_approvals`, `approve_change`, `reject_change`, `rollback_change`) to organizations the approver is an active member of via a shared `_user_active_org_ids()`/`_change_visible_to_approver()` helper pair. A change with no organization (solo/non-team accounts) is now approvable only by a platform admin — there's no team to route it to. Admins remain unrestricted, matching every other admin-gated view in the app. Regression tests: `tests/test_change_governance_org_scope.py` (6 tests: org-stamping, org-member approve, foreign-org denial on view/approve/reject, solo-change admin-only, admin sees all). **Lesson:** this repo has two independent role systems (platform `User.role` vs per-org `OrganizationMember.role`) that look similar but don't compose — any route gated by `approver_required`/`admin_required` needs an explicit org-membership check if it touches data that isn't already scoped by `user_id`, the same class of gap as the guardrails-stack and safety.py single-source-of-truth lessons above. |
| **Scheduled audit found `pagerduty_update_incident`/`opsgenie_*` alert tools unclassified in safety.py (FIXED 2026-07-18)** | Routine code-vulnerability scan flagged that `pagerduty_update_incident`, `opsgenie_acknowledge_alert`, `opsgenie_close_alert`, and `opsgenie_escalate_alert` (`src/tools/alerting_tools.py`) were absent from both `high_risk_tools` and `medium_risk_tools` in `src/agent/safety.py` — the exact `<provider>_<verb>_<noun>` blind spot documented above (name doesn't start with `update_`/`acknowledge_`/`close_`/`escalate_`, so prefix auto-detection never caught it either). Impact: the agent could silently resolve or escalate a live PagerDuty incident, or acknowledge/close/escalate an OpsGenie alert, with zero confirmation prompt — masking a real ongoing outage from on-call. Fixed by adding all four to `medium_risk_tools`; regression tests added in `tests/test_new_tools.py::TestSafetyClassifications`. No other gaps found in this pass — SSRF guard coverage, guardrail wiring on chat entry points, and the rest of the tool inventory were re-verified clean. |
| **CI pipeline outage Jul 13–15: every `Run Tests` job failed, deploys blocked 5 days (FIXED 2026-07-15)** | Every `ci.yml` run (PRs + main) failed from Jul 13 with `INTERNALERROR> SyntaxError: invalid decimal literal` after all 497 tests had already passed — so nothing deployed for 5 days while merges piled up (prod stayed healthy on old code). Root cause: **`coverage==7.15.1`** (released ~Jul 13, pulled in unpinned via `pip install pytest-cov`) crashed while generating the **HTML** coverage report: its new soft-keyword scan runs a strict `ast.parse` over every *traced* file, and Flask/Jinja compiles templates to code objects whose filename is the template path, so coverage recorded `templates/billing.html` as executed Python and choked on its CSS (line 27: `min-height: 100vh;`). Nothing was wrong with app code or tests. **Why it was hard to reproduce:** the suite passes locally without `--cov-report=html`; only the full CI flag set triggers it. coverage 7.15.2 fixed it upstream the afternoon of Jul 15 (an identical commit passed at 22:39 UTC after failing at 17:10). Fix: `ci.yml` now installs `'coverage>=7.15.2'` so runner pip caches can never resolve the broken release again (PR #48). **Debugging gotchas:** (1) the fine-grained PAT stored in git credentials cannot read Actions logs (`actions:read` missing), create PRs, or push anything touching `.github/workflows/*` — CI log access needs `gh auth login` (classic scopes) or a PAT with Actions read; (2) the GitHub failure e-mails only carry job-level pass/fail, not logs; (3) the workflow-level `GITHUB_TOKEN` is read-only in this repo, so in-run tricks that push data back to a branch don't work. **Follow-ups the same day:** PR #49 fixed the 2 real `pip-audit` findings — `click==8.3.3` (PYSEC-2026-2132) and `protobuf>=5.29.6` (PYSEC-2026-1805), the latter unblocked by bumping the unused `google-cloud-dataflow-client` 0.8.9→0.14.0 which capped protobuf `<5`; PR #50 then pinned **all 14 loose `>=` entries in requirements.txt to exact tested versions** — loose floors mean each EC2 deploy installs whatever is newest at that moment, the same untested-release failure class that caused this outage. **Policy:** keep `requirements.txt` fully `==`-pinned; bump versions deliberately through a PR so CI tests them first. Note: Copilot's "Solution for Failing Security Audit Job" text on the old failed-run pages misdiagnosed this (the Security Scan job is `continue-on-error` and never fails the pipeline) and listed vulnerabilities that were already fixed — its Jul 15 commit `c52fbaf` only loosened pins that PR #50 re-tightened. |
| **Role-ARN credential save fails: "security token included in the request is invalid" (FIXED 2026-06-12)** | Saving an IAM Role ARN in Settings failed even though the customer role + trust policy + External ID were correct (CLI AssumeRole worked). Two stacked production issues: (1) **dead AWS keys in `/var/www/devops-agent/config/.env`** — the old account's deleted key (`AKIAU4YZ…`, April incident) was still in that file. In production `init_secrets()` returns False (Secrets Manager load fails on the box), so `app.py`'s fallback loads `config/.env` FIRST (`for _env_path in ['config/.env', '.env']`), poisoning `os.environ['AWS_ACCESS_KEY_ID']` with the dead key → every platform STS call got `InvalidClientTokenId`. Fixed by deleting the `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` lines (backup: `config/.env.bak-stale-keys` on the box) — the app now falls through to the instance profile. (2) **instance role lacked `sts:AssumeRole`** — added inline policy `devops-agent-assume-customer-roles` (`sts:AssumeRole` on `*`) to `devops-agent-ssm-role`. Verified end-to-end via Playwright on production: save + Test Connection both succeed as `assumed-role/DevOpsAgentRole`. **Lessons:** the platform's AssumeRole identity is the instance profile, keep it that way (no static platform keys anywhere); `config/.env` shadows `.env` in the production fallback path — never leave stale credentials in it; debugging note: `/proc/<pid>/environ` shows exec-time env only, runtime `os.environ` writes (like dotenv fallbacks) are invisible there. |
| **Setting CREDENTIAL_ENCRYPTION_KEY without breaking existing credentials (DONE 2026-06-12)** | `UserCloudCredential._get_encryption_key()` has two divergent paths: an explicit `CREDENTIAL_ENCRYPTION_KEY` is used (near-)directly as the Fernet key, while the `SECRET_KEY` fallback runs PBKDF2-HMAC-SHA256 (600k iters, salt `devops-agent-credential-encryption-v1`). **Setting `CREDENTIAL_ENCRYPTION_KEY=<SECRET_KEY>` would therefore change the Fernet key and break all stored credentials.** The backward-compatible value is the *derived key itself*: `base64.urlsafe_b64encode(hashlib.pbkdf2_hmac('sha256', SECRET_KEY.encode(), b'devops-agent-credential-encryption-v1', 600000))`. Applied in prod: computed on the box, asserted byte-equality of both derivation paths before writing, appended to `.env`, pushed into the `devops-agent/production` secret, restarted, and verified live decrypt + AssumeRole via `/api/aws/test`. SECRET_KEY can now be rotated without touching stored credentials. |
| **Secrets Manager load failing in prod (FIXED 2026-06-12)** | `init_secrets()` returned False in all gunicorn workers ("AWS Secrets Manager failed, falling back to .env"). Root cause: the `devops-agent/production` secret **never existed in account 188046727805** — it was lost in the June 5 account migration and the app had been silently running off `.env` (via systemd `EnvironmentFile`) ever since. The instance role's `devops-agent-secrets-read` policy was fine (GetSecretValue returned ResourceNotFound, not AccessDenied). Fix: temporarily granted the instance role a write policy scoped to `devops-agent/production*`, ran `scripts/rebuild_secret_from_env.py` on the box (rebuilds the secret from `.env`; 24 keys; excludes `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` by design), verified `init_secrets()` loads, revoked the temp policy, restarted. **Debugging gotcha:** worker startup `print()` output is block-buffered — it only flushes to the journal at worker shutdown, so "Secrets Manager failed" warnings appearing during a restart belong to the *previous* worker generation's startup, not the new one. **Operational note:** managed keys (see `MANAGED_SECRET_KEYS`) are loaded from the secret at startup and take precedence — after editing one in `.env`, re-run the rebuild script (needs a temporary write grant) or update the secret directly. |
| **"File has not been read yet" error** | After context compression, must re-read the file section before editing. This is a Claude Code limitation — always `Read` before `Edit`. |
| **Unregistered functions** | Functions can exist in tool files but not be in `get_tools()`. Verify with the unregistered function finder command below. |
| **K8s extra API clients** | `_get_k8s_client()` only returns `(CoreV1Api, AppsV1Api)`. For Ingress use `client.NetworkingV1Api()`, for Jobs use `client.BatchV1Api()` — create inline after calling the helper. |
| **AWS thread-local credentials** | `_get_boto_client()` uses thread-local storage for per-user credentials. Never create boto3 clients directly or credentials won't be isolated. |
| **Azure async operations** | Most Azure write operations use `begin_*()` returning a poller. Must call `.result()` to wait for completion or the operation may not finish. |
| **GCP project resolution** | Always use `_resolve_project_id(project_id)`. Resolution order: explicit param > per-user credentials > `GOOGLE_CLOUD_PROJECT` env var. |
| **Safety.py must be updated** | Every new delete tool MUST be added to `high_risk_tools` in `safety.py`. Forgetting this silently defaults to low risk with no confirmation. |
| **Test fixtures flaky** | Existing test suite has pre-existing SQLite unique constraint failures in `conftest.py`. These are unrelated to tool changes. |
| **IAM role deletion** | AWS `delete_iam_role` requires cleanup: detach managed policies, delete inline policies, remove from instance profiles — all before the role itself can be deleted. |
| **Billing payment bypass (FIXED)** | Legacy endpoints `/api/subscription/upgrade` and `/api/credits/purchase` granted free credits without Stripe payment. Now return 403. All credit granting goes through Stripe webhook `handle_checkout_completed()`. |
| **CI deploy: SSH key via Secrets Manager fails** | `ci.yml` was fetching EC2 SSH key from `devops-agent/prod/secrets` in AWS Secrets Manager, but that secret does not exist. Fixed by reading `EC2_SSH_KEY` directly from a GitHub secret instead. Set `EC2_SSH_KEY` in repo Settings → Secrets → Actions. |
| **SSM deploy: empty CommandId / stuck "Pending" (FIXED)** | After migrating to AWS account `188046727805`, `deploy.yml` failed: `aws ssm send-command` returned an **empty `CommandId`** (`ParamValidation: Invalid length for parameter CommandId, value: 0`) → 60 Pending polls → "Timed out waiting for deploy". Root cause: the EC2 instance `i-09af962714b13f9bc` had **no IAM instance profile** in the new account (`IamInstanceProfile=null`), so the SSM agent had no credentials and never registered (`describe-instance-information` empty). Fix: created role `devops-agent-ssm-role` (trust `ec2.amazonaws.com` + `AmazonSSMManagedInstanceCore`), instance profile `devops-agent-ssm-profile`, associated it with the instance, then **restarted the SSM agent** (`sudo systemctl restart snap.amazon-ssm-agent.amazon-ssm-agent` via EC2 Instance Connect — it had backed off after the earlier credential failures). Instance then went Online. Also fixed three stale assumptions in `deploy.yml`'s script: repo path `/var/www/devops-agent` (not `/home/ubuntu/app/DevOps-Agent`), venv `…/venv`, health port `8000` (not `5000`). Private-repo pull (SSM runs as root, no token, everything CloudTrail-logged) is handled by a **read-only SSH deploy key** on the box (`/home/ubuntu/.ssh/deploy_key` via the repo's `core.sshCommand`) — never inject a token through SSM parameters. **Remote-URL conflict:** `ci.yml`'s deploy rewrites `origin` back to HTTPS (token-injected) on every push, which clobbers the SSH remote and makes the next SSM deploy fail with `could not read Username for 'https://github.com'`. Fix: `deploy.yml` now re-sets `origin` to the SSH URL + `core.sshCommand` at the start of every run (self-contained, idempotent). Also note the `EC2_INSTANCE_ID` GitHub secret must hold the **current** instance id (`i-09af962714b13f9bc`) — a stale value after the account migration made `send-command` produce an empty `CommandId`. `deploy.yml` is now `workflow_dispatch`-only; the auto-deploy stays in `ci.yml` (EC2 Instance Connect). |
| **CI deploy aborts: "untracked working tree files would be overwritten by merge" (FIXED)** | `ci.yml`'s deploy used `git pull origin main` (a merge), which aborts if the EC2 box has an untracked file colliding with an incoming tracked file (seen with a root-owned `scripts/restore_prod_locally.py` that had been copied to the server). Fix: `ci.yml` now does `git fetch origin main` + `git reset --hard origin/main` (same robust pattern as `deploy.yml`) — force-syncs to origin and overwrites such files instead of aborting. Recovery for a stuck box: `sudo -u ubuntu git -C /var/www/devops-agent fetch origin main && sudo -u ubuntu git -C /var/www/devops-agent reset --hard origin/main`. |
| **IAM key rotation breaks CI** | If `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` GitHub secrets become invalid (rotated or deactivated), both `ci.yml` and `deploy.yml` fail at "Configure AWS credentials" with `The security token included in the request is invalid`. Fix: create a new IAM access key (`aws iam create-access-key --user-name abi-dev`) and update both GitHub secrets. |
| **Stripe price IDs not loading in production** | `MANAGED_SECRET_KEYS` in `secrets_manager.py` was missing Stripe price IDs. Added all `STRIPE_PRICE_*` and `STRIPE_PUBLISHABLE_KEY` to the list. Must also be added to AWS Secrets Manager JSON. |
| **Credit pack size mismatch** | Billing page showed packs of 50/200 but Stripe config has 100/250. Fixed billing.html to match Stripe: 100/$10, 250/$20, 500/$35, 1000/$60. |
| **Developer REST API bypassed the guardrails stack (FIXED 2026-07-11)** | Surfaced by the daily guardrails-focused rotating security review (`services/input_sanitizer.py` + `src/agent/guardrails.py`). `routes/api_gateway.py`'s `/v1/agent` and `/v1/agent/stream` (the Professional/Business developer API) only called `validate_message()` (the 10-regex pattern check). They never called `sanitize_input()`, never checked `is_guardrail_blocked()`, and never called `screen_message()` — so the Haiku semantic jailbreak/malware/exfiltration screen and the fail-closed crisis (self-harm) keyword detector never ran on this path, and repeated abuse was never recorded or throttled via the account lockout. Unlike `/api/chat`/`/api/chat/stream` (`app.py`) and `api/v1/conversations.py`, which all run the full stack, this third entry point into the same tool-executing agent (real AWS/Azure/GCP/K8s access) was effectively unguarded beyond regex matching. Fix: both routes now run the same sequence as the other two guardrail-gated entry points — `sanitize_input()` → `User.is_guardrail_blocked()` → `validate_message()` (+`record_guardrail_violation()` on block) → `screen_message()` (+`record_guardrail_violation()` on block) — before the message reaches `process_message_isolated`/`process_message_streaming`. **Lesson:** like the safety.py risk-classification rule, the guardrails stack has no single enforcement point (each route wires it manually) — any new message-accepting endpoint must be checked against the full sequence in CLAUDE.md's Guardrails section, not just `validate_message()`. |
| **MCP connector auth fails across gunicorn workers — `invalid_grant` (FIXED)** | The claude.ai / Claude Desktop connector could complete browser sign-in but the connection stayed "unauthorized" (broken for ~3 months). Root cause: `routes/mcp.py` stored OAuth **authorization codes in per-process memory** (`_oauth_codes` dict). Production runs **4 gunicorn workers**, and the connector load-balances `/oauth/authorize` (issues the code) and `/oauth/token` (exchanges it) to *different* workers — so the worker doing the token exchange never had the code → `invalid_grant: Code expired or invalid` → no token → failed connect. ~75% failure with 4 workers; the discovery/registration endpoints all worked in isolation, which masked it. Fix: persist auth codes to the DB (new `MCPOAuthCode` model / `mcp_oauth_codes` table) via `_store_code_db()` / `_consume_code_db()`, mirroring the already-DB-backed token pattern (`MCPOAuthToken`). Codes are single-use (atomic delete-by-code on exchange) and the table is created automatically by `db.create_all()` on startup. The in-memory dict remains only as a same-worker fallback if the DB write fails. **Lesson:** any per-process dict on a multi-step OAuth/session path is a latent multi-worker bug — use the DB (or a shared store), not module-level memory. |
| **REST API `/v1/tools/execute` bypassed the safety validator (FIXED 2026-07-09)** | Surfaced by the daily cloud vulnerability-review routine (`trig_01XqjDY8x5M6gWHXwTruMEeH`). `api/v1/tools.py` had its own `_is_high_risk()` with a hardcoded 12-tool set + 6 prefixes instead of calling `SafetyValidator.validate_tool_call()`. Result: a **write-scope API key** could `POST {"tool":"execute_command",...}` to `/api/v1/tools/execute` and get arbitrary shell/cloud execution **with no `confirm:true` gate** — same for `ssm_run_command`, the generic `aws/azure/gcp/k8s_api_write` passthroughs (marked "always high-risk" in safety.py), and the *entire* `medium_risk_tools` set (IAM changes, SG edits, EC2 stop/reboot, secret updates), none of which the endpoint checked at all. The chat UI and MCP server already routed through `SafetyValidator`; only this REST path diverged. Fix: deleted the local `_is_high_risk`/`_HIGH_RISK_TOOLS`/`_HIGH_RISK_PREFIXES` duplication and route every call through a module-level `SafetyValidator().validate_tool_call()` — `is_safe=False` → 403, `requires_confirmation` (high **and** medium) → 409 unless `confirm:true`. Regression-tested in `tests/test_api_tools_execute.py` (10 tests; verified they fail against the old code — `execute_command`/`aws_api_write`/`ec2 stop` returned 200 unconfirmed before). **Lesson:** risk classification must have exactly one source of truth (`safety.py`); any endpoint that re-implements it will drift and silently under-protect — the CLAUDE.md "always add new delete_/update_ tools to safety.py" rule only works if every executor actually calls safety.py. |
| **MCP connector "still unauthorized" after successful sign-in (FIXED 2026-07-08)** | For ~2 months the claude.ai "Devops Agent" connector completed browser sign-in but stayed unauthorized. Evidence trail: nginx showed the full OAuth dance succeeding (authorize 302 → `POST /mcp/oauth/token` 200) and 12 `MCPOAuthToken` rows piled up in the prod DB for user 1 — yet in 7 days of app logs **no request ever carried a Bearer token** (every MCP hit logged "no bearer token in request"). Root cause: the connector was configured with the **bare origin** `https://mcp.devopsagent.io` (no `/mcp` path). Its JSON-RPC probe POSTed to `/` → the GET-only landing route → **405**; and the root `/.well-known/oauth-protected-resource` advertised `resource: …/mcp`, mismatching the root URL the client was bound to, so the client discarded every token it earned. Fix (`routes/mcp.py` + `app.py`): (1) serve the MCP streamable transport at **`POST /`** (`mcp_root_streamable` on `mcp_oauth_alias_bp`; GET `/` stays the landing page); (2) make the protected-resource metadata **path-aware** — root doc advertises the origin root, `/mcp`-suffixed doc advertises `…/mcp`; (3) 401 `WWW-Authenticate` challenges now point at the path-matching metadata doc (`_resource_metadata_url()`); (4) added RFC 8414 path-variant alias `/.well-known/oauth-authorization-server/mcp`. Regression-tested end-to-end in `tests/test_mcp_oauth.py` (DCR → PKCE authorize → token → initialize on both `/` and `/mcp`). **Follow-up hardening (same day):** brought the OAuth layer to full current-spec compliance so claude.ai's gateway has nothing left to object to — **rotating refresh tokens** (RFC 6749 §6; `MCPOAuthToken.token_kind` access/refresh, 30d/90d TTLs, single-use rotation, refresh tokens never authenticate requests), **RFC 7591 DCR echo** (`grant_types`/`response_types`/`client_name` in the registration response), **RFC 9207 `iss`** in authorization responses (+ metadata flag), **`Cache-Control: no-store`** on token responses, and a redirect_uri scheme guard (https or loopback http only — Claude Desktop/Code use `http://localhost:<port>`). **Lesson:** when OAuth "succeeds" but the client stays unauthorized, diff what the client was *configured* to talk to against what the metadata *advertises* — a resource/URL mismatch makes strict clients silently drop valid tokens. |
| **MCP connector OAuth 404 on /authorize (FIXED)** | Connecting the `mcp.devopsagent.io` MCP server failed: client redirected to `https://mcp.devopsagent.io/authorize` → 404. Two root causes: (1) `mcp.devopsagent.io` was a DNS-only Cloudflare record hitting EC2 directly with a **self-signed cert** → `SEC_E_UNTRUSTED_ROOT`. Fixed by setting the `mcp` record to **Proxied** + SSL/TLS mode **Full** (Cloudflare passes the `Authorization` header through, so the subdomain no longer needs to bypass the proxy). (2) `_mcp_base_url()` hardcoded the apex (`MCP_BASE_URL` default `https://devopsagent.io`), so the OAuth metadata `issuer` was `devopsagent.io` while the connector talked to `mcp.devopsagent.io`. RFC 8414 issuer-mismatch → client discarded the metadata and fell back to the default `/authorize` path on the origin (404, since the real endpoint is `/mcp/oauth/authorize`). Fixed by making `mcp_base_url()` (now in `routes/mcp.py`) **host-relative** — it derives the issuer/endpoints from the request `Host` (whitelisted to `*.devopsagent.io`, forced https) so the issuer always matches the host in use. Also added root-level OAuth aliases (`/authorize`, `/token`, `/register` via `mcp_oauth_alias_bp`) for clients that probe origin-default paths instead of reading the metadata. |
| **MCP connector OAuth silently fails on every attempt — `invalid_grant` regardless of worker/DNS fixes (FIXED 2026-07-07)** | Even after the multi-worker code-storage fix and the host-relative issuer fix above, the connector still could not authenticate — every code exchange failed. Root cause: `_consume_code_db()` (`routes/mcp.py`) called `.timestamp()` directly on `MCPOAuthCode.expires_at`, a **naive datetime holding a UTC value** (from `datetime.utcnow()`). Python's `datetime.timestamp()` on a naive object assumes **local server time**, not UTC, so the computed expiry silently shifted by the server's UTC offset before being compared against the true UTC `time.time()`. On a server whose local timezone is ahead of UTC, a code issued moments ago reads as already expired by the full offset — reproduced in isolation: on TZ `Pacific/Kiritimati` (UTC+14) a freshly-issued 5-minute code appeared ~14 hours expired, guaranteeing `invalid_grant` on every single attempt. Fixed by tagging the datetime as UTC before converting (`row.expires_at.replace(tzinfo=timezone.utc).timestamp()`). Regression test: `tests/test_mcp_oauth.py` (simulates a non-UTC server clock via `TZ`/`time.tzset()`). **Lesson:** never call `.timestamp()` on a naive datetime that represents UTC — either attach `tzinfo=timezone.utc` first, or compare naive `datetime.utcnow()` values directly instead of round-tripping through epoch seconds. |
| **Subscription price mismatch (FIXED)** | `create_stripe_prices.py` had $49/$199/$799 while billing page showed $10/$30/$100. Aligned everything to $29/$99/$299. Business tier changed from unlimited to 10,000 credits. Old Stripe prices were inactive — must run script to create new active prices. |
| **`resolve_model_for_tier('free')` no longer returns Groq** | Free tier now maps to `claude-sonnet-4-6` (Anthropic). All Groq fallback paths must use explicit `ModelConfig(provider='groq', model='llama-3.3-70b-versatile', ...)` or the `GROQ_FALLBACK_MODEL` constant in `chat_service.py`. Never call `resolve_model_for_tier('free')` when you need a Groq config. |
| **Free-tier credit exhaustion returns 200, not 402** | When free-tier users run out of credits, endpoints return a 200 with `generate_upgrade_pitch()` and `trial_ended: true`. Only paid users get a 402. Frontend checks `trial_ended` in the SSE `done` event to show the upgrade CTA. |
| **Injection patterns were log-only (FIXED)** | `input_sanitizer.py` originally logged injection patterns but never blocked them. Now `validate_message()` returns `(False, reason)` on any match — callers must check the return value and reject the message. `sanitize_input()` still just cleans chars; call `validate_message()` separately for policy enforcement. |
| **Guardrail screen fails open** | `screen_message()` in `guardrails.py` catches all exceptions and returns `blocked=False`. This is intentional — an Anthropic outage should not take down the chat endpoint. Pattern-matching in `validate_message()` is always the first line of defense. |
| **MonitoringRule.to_dict() missing fields** | `pending_since` and `firing_since` were not serialized. Always include them — templates and API clients rely on these to show time-in-state. |
| **Alert history unbounded growth** | `ProactiveMonitoringService.alert_history` had no size cap. Capped at 500 entries (`_max_alert_history`). Trim on append. |
| **Monitoring notification only fired on 'firing'** | `send_alert_notification()` in `app.py` only handled `event_type == 'firing'`. Changed to `in ('firing', 'resolved')` so resolution notifications are also sent. |
| **Built-in playbook IDs mismatch (FIXED)** | `routes/incidents.py` protection list had `disk-full` and `pod-crash-loop` which don't match registered IDs (`disk-space-low`, `pod-crashloop`). Also `high-error-rate`/`latency-spike` were referenced but never registered. Corrected list: `high-cpu-usage`, `memory-pressure`, `disk-space-low`, `pod-crashloop`, `service-down`, `security-alert`. |
| **Missing incident action handlers** | `ActionType.FAILOVER`, `ROLLBACK`, and `ROTATE_CREDENTIALS` were defined in the enum but had no registered handlers. Calling a playbook that uses them raised KeyError. Stub handlers added to `incident_response.py`. |
| **root_cause_analyzer invalid model (FIXED)** | Used `claude-sonnet-4-20250514` which is not a valid model ID — analysis API calls were failing. Changed to `claude-sonnet-4-5-20250929`. |
| **Analysis dashboard dict vs object access** | `get_all_analyses()` returns `list[dict]` but `templates/analysis/dashboard.html` used dot notation (`analysis.id`). Must use bracket notation (`analysis['id']`). |
| **CostOptimization status='active' wrong (FIXED)** | Dashboard sync route queried `status='active'` but the model uses `status='pending'`. Cost savings notifications never fired. Changed to `'pending'`. |
| **Azure/GCP resource.metadata vs resource_metadata (FIXED)** | `infrastructure_sync.py` used `resource.metadata` for Azure VMs, SQL, GCP compute, and GKE — but the column is `resource_metadata`. 5 occurrences replaced with `resource_metadata`. |
| **RDS metadata missing db_instance_identifier** | `sync_aws_rds_instances()` stored `db_class` but not `db_instance_identifier`. `app.py` line 2873 expects this key for utilization lookup — was silently returning empty. |
| **Analytics routes calling non-existent methods (FIXED)** | `routes/analytics.py` called 6 methods that didn't exist on `AnalyticsService`: `get_cost_analytics`, `forecast_costs`, `get_resource_utilization`, `get_alerts_summary`, `get_deployment_stats`, `get_incident_stats`. All added. Also `get_time_series()` was called with 3-4 args but only accepts 2. Routes fixed to use correct signatures. |
| **Analytics period parsing crash** | `int(period.replace('d', ''))` crashes for `'24h'`. Changed to `int(period.rstrip('dh'))` with a guard. |
| **DriftReport.drifted_resources is int not list** | `len(report.drifted_resources)` raised `TypeError`. It's already an int count — use directly without `len()`. |
| **API Gateway decorator called wrong methods (FIXED)** | `api_key_required` called `validate_api_key()` (doesn't exist → use `get_api_key_by_key()`) and treated `check_rate_limit()` return as bool (it returns `tuple(bool, dict)` — must unpack). |
| **API Gateway usage stats method name** | `service.get_usage_stats()` doesn't exist. Correct method is `get_api_usage_stats()`. |
| **Compliance service/route API mismatch (FIXED)** | Routes called ~22 methods that don't exist on `ComplianceService` (e.g., `get_enabled_frameworks`, `get_framework_controls`, `get_violations`, etc.). Added adapter methods to the service class. Routes also called `enable_framework(framework_id)` and `run_compliance_check(framework_id)` with wrong signatures — fixed to pass `user_id` and `framework_name`. |
| **Contact widget blocks send button on mobile** | Fixed: floating contact button (`position:fixed; bottom:24px; right:24px`) overlaps the send button on mobile. Hidden with `display:none` inside `@media (max-width: 768px)` in `templates/index.html`. |
| **RateLimitExceeded shows as 500 (FIXED)** | `@app.errorhandler(Exception)` intercepted `RateLimitExceeded` before Flask handled it as 429, rendering the 500 template. Fixed by adding a dedicated `@app.errorhandler(RateLimitExceeded)` handler above the generic one. Returns JSON `{error: ...}` with 429 for API/chat routes, inline HTML for page routes. Import: `from flask_limiter.errors import RateLimitExceeded`. |
| **`resolve_model_for_tier('free')` now returns Kimi** | Free and Starter tiers default to `kimi` provider. Use `resolve_model_with_preference(tier_name, preferred_provider)` to respect user overrides. The `provider` parameter on `process_message_isolated()` and `process_message_streaming()` routes to `_call_kimi_api()` when set to `'kimi'`. |
| **Kimi tool format differs from Anthropic** | Anthropic uses `{name, description, input_schema}`. Kimi (OpenAI-compatible) uses `{type: "function", function: {name, description, parameters}}`. `_convert_tools_to_openai_format()` in `core.py` handles the conversion. |
| **Kimi reasoning models reject temperature != 1 (FIXED, regressed & re-fixed 2026-07-23)** | All `kimi-k*` models (K2.5 through K3) are reasoning models that only accept `temperature=1`; passing `temperature=0.7` causes a 400. Originally fixed in `core.py` by skipping the `temperature` param when `'k2' in model` — but the 2026-07-22 default-model bump to `kimi-k3` broke that string match (no `k2` in `kimi-k3`), reintroducing the 400 in production. Re-fixed by inverting the check: only send `temperature` when `model.startswith('moonshot-v1')` (the non-reasoning legacy family), so it's correct for any future `kimi-k*` model without further edits. |
| **Kimi reasoning_content missing in tool calls (FIXED)** | Kimi K2.5 streams `reasoning_content` (thinking tokens) that must be preserved in assistant messages during multi-turn tool-use conversations. If omitted, subsequent API calls fail with "thinking is enabled but reasoning_content is missing". Fixed by collecting `reasoning_content` from streaming deltas and including it in the assistant message dict. |
| **AWS dual-mode auth (access keys + role ARN)** | `credential_service.py` supports both `auth_mode='access_key'` (direct keys) and `auth_mode='role_arn'` (STS AssumeRole with temp creds). Settings UI has toggle. Small teams use access keys; enterprise uses cross-account role delegation. |
| **11 missing DB columns caused 500 error (FIXED)** | New model fields (`preferred_model_provider`, `learning_mode`, `sandbox_mode`, `learning_level`, `email_verified`, `email_verification_token`, `email_verification_sent_at`, `password_reset_token`, `password_reset_expires`, `guardrail_violations`, `guardrail_blocked_until`) weren't in the DB. Fixed by running `migrate_missing_columns.py`. |
| **Env var name mismatch for Kimi (FIXED)** | `.env` had `kimi_API_KEY` but code reads `MOONSHOT_API_KEY`. Renamed in `.env`. |
| **NGN payments simplified to Stripe (FIXED)** | Replaced Paystack (primary) + Flutterwave (fallback) with Stripe NGN currency support. Deleted `services/paystack_integration.py`, `services/flutterwave_integration.py`, `scripts/create_paystack_plans.py`, `scripts/create_flutterwave_plans.py`. Existing Stripe checkout routes now accept `currency` param. NGN Stripe Price IDs stored in `NGNPriceConfig.stripe_price_id_ngn`. Run `scripts/create_stripe_ngn_prices.py` to create NGN prices in Stripe. |
| **Env file load order: `config/.env` wins (CRITICAL)** | App loads `config/.env` first, then `.env`, both with `override=False`. First-loaded value wins. Always update `config/.env` when changing env vars — `.env` is a fallback only. Missing `STRIPE_PRICE_BUSINESS` in `config/.env` caused checkout to fail even though `.env` had the value. |
| **`base.html` template missing (FIXED)** | 27 blueprint templates (analytics, compliance, ai_infrastructure, etc.) extend `base.html` but it didn't exist. Created `templates/base.html` with full layout (header nav, fonts, CSS variables, responsive design). |
| **Auto-migration at app startup (ADDED)** | `db.create_all()` only creates new tables, never adds columns to existing tables. Added auto-migration after `db.create_all()` that inspects all models, compares columns to DB, and runs `ALTER TABLE ADD COLUMN IF NOT EXISTS` for missing ones. Eliminates the need to run `migrate_missing_columns.py` manually. |
| **Webhook user lookup by email only (FIXED)** | `handle_checkout_completed()` looked up users by `customer_email` only — if email didn't match, payment was silently lost. Now stores `user_id` in Stripe session metadata; webhook looks up by `user_id` first, falls back to email. |
| **`stripe_customer_id` never saved (FIXED)** | `handle_checkout_completed()` never stored `stripe_customer_id` from the Stripe session onto `UserSubscription`. This broke ALL recurring billing webhooks (`invoice.payment_succeeded`, `invoice.payment_failed`, `customer.subscription.updated/deleted`) which look up by `stripe_customer_id`. Now saved on every checkout. |
| **Recurring billing webhook lookup fallback (FIXED)** | `handle_invoice_payment_succeeded` and `handle_invoice_payment_failed` only looked up by `stripe_customer_id`. Added fallback to `stripe_subscription_id` lookup, and backfills `stripe_customer_id` when found. |
| **Subscription metadata not on Stripe Subscription object (FIXED)** | Checkout session metadata (`tier_name`, `user_id`) was only on the session, not on the resulting Stripe Subscription. Added `subscription_data={'metadata': metadata}` to session creation so metadata propagates to the subscription object for future webhook events. |
| **Billing success page was a no-op (FIXED)** | `/billing/success` retrieved the Stripe session but did nothing (`pass`). If webhook hadn't fired yet, user saw no subscription update. Now processes checkout inline as a safety net (with idempotency checks to avoid double-granting). |
| **Missing analytics templates (FIXED)** | Routes referenced `analytics/costs.html`, `analytics/performance.html`, `analytics/resources.html` but templates didn't exist. Created all three. |
| **AI Infrastructure route broken method calls (FIXED)** | `routes/ai_infrastructure.py` called non-existent methods on `AIInfrastructureService`. Fixed 6 calls: `get_templates()` → `get_user_templates(user_id)`, `get_recommendations()` → `get_recommendations(user_id)`, `get_deployments()` → `get_user_deployments(user_id)`, etc. Added `get_user_deployments()` and `get_user_deployment()` stubs to service. |
| **Zombie server processes on port 5000** | Multiple stale `python app.py` processes can accumulate on port 5000. Browser may hit an old process without code fixes. Always kill all Python processes before restarting: `taskkill /F /IM python.exe` (Windows) or `pkill -f 'python app.py'` (Linux). |
| **Prometheus URL hardcoded (FIXED)** | `proactive_monitoring.py` used hardcoded `http://localhost:9090`. Now reads `os.environ.get('PROMETHEUS_URL', 'http://localhost:9090')`. Add `PROMETHEUS_URL` to `.env` for non-local Prometheus. |
| **Monitoring threshold validation missing (FIXED)** | `routes/monitoring.py` passed `data['threshold']` to `float()` without try/except. Non-numeric values caused 500. Now returns `{'error': 'Threshold must be a numeric value'}` with 400. |
| **ANSIBLE_PLAYBOOK and CUSTOM handlers missing (FIXED)** | `ActionType.ANSIBLE_PLAYBOOK` and `ActionType.CUSTOM` had no registered handlers in `incident_response.py`. Playbooks using them silently failed and incidents never auto-resolved. Stub handlers added in `_register_default_handlers()`. |
| **`_handle_block_ip` ignored AWS failures (FIXED)** | SG path in `_handle_block_ip` always returned `success: True` regardless of `authorize_security_group_ingress()` result. Now checks `result.get('success')` like all other handlers. |
| **`_save_incident_to_db` missing user_id filter (FIXED)** | Queried `IncidentModel.query.filter_by(incident_key=...)` without `user_id`. Added `user_id=user_id` for proper isolation. |
| **Azure/GCP test endpoints missing (FIXED)** | Settings page called `/api/azure/test` and `/api/gcp/test` but endpoints didn't exist in `app.py`. Added both — Azure tests via `SubscriptionClient.subscriptions.list()`, GCP via `cloudresourcemanager.projects().get()`. |
| **GCP credentials never saved (FIXED)** | `settings.html` POST to `/api/gcp/config` sent field `service_account_key` but handler reads `credentials_json`. Credentials silently saved as empty. Fixed field name in `settings.html`. |
| **Frontend↔backend field name mismatches** | Common pattern: frontend `fetch()` calls use different JSON keys or endpoint URLs than the backend expects. Always cross-check every `fetch()` URL and payload key in templates against actual route handlers in `app.py` and `routes/`. |
| **`column tool_trace/page_context does not exist` on PostgreSQL** | New `ChatMessage` columns added to model but never migrated to DB. Fix: (1) auto-migration now runs at every startup — catches all missing columns. (2) `ChatMessage.query` uses explicit column selection (`role`, `content` only) so `SELECT` never hits missing columns. (3) assistant INSERT uses `no_autoflush` + try/except fallback that strips new fields if column missing. |
| **`Another request is already streaming for this conversation.`** | `is_streaming=True` committed but error crashed before `finally` block reset it. Fix: (1) outer `except` handler now resets `is_streaming=False`. (2) guard stamps `updated_at=now()` when acquiring lock. (3) stale locks >90s auto-reset before the guard check. (4) `POST /api/reset-streaming` clears all stuck locks for current user. |
| **Incidents 500 on load (UndefinedColumn correlation_group_key)** | `_ensure_user_loaded` did `IncidentModel.query` (`SELECT *`) which hit missing `correlation_group_key`. Wrapped in try/except — returns empty incidents list instead of crashing. Permanent fix: auto-migration adds the column on next restart. |
| **Auto-migration documented but not implemented (FIXED)** | CLAUDE.md said "Added auto-migration after db.create_all()" but app.py only had `db.create_all()` with no column inspection. Now implemented: after `db.create_all()` at startup, inspector iterates all SQLAlchemy models and runs `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for missing columns. |
| **Developer API `/v1/conversations` chat routes skipped `sanitize_input()` (FIXED — security)** | A routine security review found `api/v1/conversations.py`'s `send_message()` and `api_v1_chat_stream()` — a third chat-to-agent surface alongside `app.py`'s web routes and `routes/api_gateway.py`'s developer API — called `validate_message()`/`screen_message()` directly on the raw request body, never calling `sanitize_input()` first. `validate_message()`'s own docstring assumes "already-sanitized" input; skipping the step reintroduces the same gap already fixed twice elsewhere (`routes/api_gateway.py`, see below) — Unicode control/format characters can fragment or hide a prompt-injection pattern from the regex checks when sanitization is skipped. Fixed by sanitizing the message immediately after extracting it from the request body, before any guardrail check, in both handlers — matching the order used everywhere else. **Also found in the same review:** 4 tools missing risk classification in `src/agent/safety.py` so they executed with zero confirmation prompt — `add_iam_user_to_group` (IAM privilege-escalation vector, aws_tools.py) and `create_eventbridge_rule` (aws_tools.py) added to `medium_risk_tools`; `manage_vm` (azure_tools.py, action-aware: start/stop/restart/deallocate) and `manage_compute_instance` (gcp_tools.py, action-aware: start/stop/reset) given the same action-aware special-casing as `manage_ec2_instance` so stop/restart/deallocate/reset now require confirmation. **Lesson:** whenever a new route forwards free-text user input to the agent, grep for all 4 guardrail-stack calls (`sanitize_input`, `is_guardrail_blocked`, `validate_message`, `screen_message`) and diff against the other entry points — new chat surfaces keep getting added without the full stack. |
| **MCP OAuth: `/authorize` never validated `redirect_uri`, and refresh tokens had no client binding (FIXED — security)** | A security review found `oauth_authorize()` (`routes/mcp.py`) accepted *any* `client_id` and never checked `redirect_uri` against that client's registered value — an attacker could reuse a real/guessable `client_id` with their own `redirect_uri`, phish a victim into signing in on the real domain, and have the auth code redirected straight to an attacker server (account takeover). Also: the new `refresh_token` grant performed no client authentication at all, so a leaked refresh token could be redeemed by anyone without the client's secret. Fixed: (1) added `MCPOAuthClient` DB model (`mcp_oauth_clients` table) so dynamically-registered clients (RFC 7591) are visible across gunicorn workers, same pattern as `MCPOAuthCode`/`MCPOAuthToken`; `/authorize` now 400s on an unregistered `client_id` and on a `redirect_uri` not in that client's registered list. (2) `MCPOAuthToken` gained a `client_id` column; `_consume_refresh_token_db()` now rejects a refresh token redeemed under a different `client_id` than it was issued to, and requires `client_secret` when the token was issued to the built-in confidential client. (3) `_AUTHORIZE_HTML` now shows the requesting client's name so a mismatched/unknown app is visible to the user instead of looking like a bare login form. (4) `mcp_base_url()`'s host-allowlist check (`host.endswith('devopsagent.io')`) was missing a dot boundary, letting a lookalike domain (`notdevopsagent.io`) pass — fixed to require an exact match or a `.devopsagent.io` suffix. (5) the 4 remaining hand-rolled error responses in `oauth_token()` were switched to the `_token_error()` helper so `Cache-Control: no-store` (RFC 6749 §5.1) applies to all of them, not just the new refresh-token paths. Tests updated in `tests/test_mcp_oauth.py` to register clients via DCR before calling `/authorize` (matching real client behavior), plus new tests for the unregistered-client and redirect_uri-mismatch rejections and refresh-token client binding. |
| **Direct signup granted platform-wide `admin` role to every new user (FIXED — critical security)** | A routine security review found `signup()` (`routes/auth.py`) unconditionally set `role='admin'` on every new `User`, but `/admin/*` (`routes/admin.py`) has no per-tenant/org scoping — every query is a bare `User.query`/`UsageLog.query` across all users. Concretely: anyone could sign up with a throwaway email and immediately get `/admin/` dashboard access to every platform user's email/role/activity, the global audit log, and (via `user_can_manage_user()`, which only compares role *level*) the ability to lock, unlock, or **delete** any account with a lower role. This directly contradicted CLAUDE.md's own documented policy (`user` = "default for new signups"; "no self-serve promotion — must be done directly in the database") and the SSO JIT-provisioning path (`services/sso_service.py`), which correctly assigns `role='user'` — the direct-signup path was the sole, inconsistent outlier, introduced in the commit that added the daily vulnerability-scan workflow and never revised since. Fixed by changing the signup default to `role='user'`, matching SSO and the documented Role Hierarchy; granting admin still requires the direct-DB-edit procedure in CLAUDE.md's "Granting Admin Access" section. **Also found in the same review and fixed:** (1) `_get_gitlab_base_url()` (`src/tools/cicd_tools.py`) — the only caller-supplied-URL tool in the file that skipped `assert_safe_url()`, an SSRF gap reaching all 9 GitLab CI/CD tools (e.g. `gitlab_url=http://169.254.169.254/...` hit the cloud metadata endpoint unmitigated); now validated like every Jenkins call site in the same file. (2) 27 destructive/sensitive tools with no `src/agent/safety.py` risk classification, executing with zero confirmation prompt — most notably `ansible_playbook_run`/`ansible_adhoc_command`/`execute_script` (arbitrary code execution, same risk class as `execute_command`) and `git_delete_branch`/`git_delete_tag` (destructive, but the `git_` prefix defeats the `delete_` auto-detect fallback); the rest were AWS/GCP/K8s/CI-CD/Ansible tools whose already-classified sibling (delete/detach/revoke counterpart) highlighted the gap — see the two new comment blocks in `safety.py`'s `high_risk_tools`/`medium_risk_tools` sets for the full list. (3) `User.verify_mfa_otp()` (`models.py`) compared the OTP hash with plain `==` instead of `secrets.compare_digest`, inconsistent with `services/two_factor_service.py`'s backup-code check — switched to constant-time comparison. (All items flagged in this review have since been fixed — SSRF-guard redirect gap, the shared `agent` singleton race, and the login-timing side channel below; see those entries. The DNS-rebinding TOCTOU on the SSRF guard is a known, deliberately deferred residual gap — see that entry.) |
| **Login-timing side channel let an attacker enumerate valid emails/usernames (FIXED 2026-07-24)** | Flagged in the review above, investigated further: `routes/auth.py`'s `login()` returned immediately for an unknown email/username (`if not user: return render_template(...)`) *before* ever calling `User.check_password()` — but for an existing account with the wrong password, it always ran `check_password()`, which does `bcrypt.checkpw()`, a deliberately slow comparison (tens of ms at the default cost factor). Both cases render the identical error text ("Invalid email/username or password"), but the response *time* differs by roughly bcrypt's full cost — enough to distinguish "no such account" from "account exists, wrong password" purely by timing, letting an attacker enumerate valid accounts against `/login` even though the error message gives nothing away. Fixed with `_run_timing_safe_password_check()`: when no user is found, it still runs `bcrypt.checkpw()` against a fixed dummy hash (`_DUMMY_PASSWORD_HASH`, same 12-round cost factor as `User.set_password()`'s `bcrypt.gensalt()` default) before the early return, so both paths pay the same dominant cost. The `sso_login_required()`/`is_locked()` checks still only run for existing accounts (cheap logic/DB reads, not additional hashing — negligible next to bcrypt's cost) so this isn't byte-for-byte identical control flow, just equalized on the signal that actually matters. Regression tests in `tests/test_auth.py::TestLoginTimingSideChannel` assert on the *mechanism* (bcrypt always invoked, dummy hash used when no account exists) rather than wall-clock timing, which would be flaky under CI load; verified they fail against the pre-fix code (both via `ImportError`/`AttributeError` for the removed helper, confirming they exercise the actual fix). **Related, fixed same day (see entry directly below):** `forgot_password()` already avoided leaking existence via response *text* (always shows the same generic success message) but still did a DB write + outbound email send only when the account exists — a residual timing signal of the same class, actually larger than login's. |
| **Forgot-password timing side channel — response time leaked account existence via the email send (FIXED 2026-07-24)** | Flagged as a related residual in the entry above, then fixed the same day: `forgot_password()` already rendered the identical generic success message regardless of whether the account existed, but for an existing account it did a DB write (token persistence) plus a *synchronous* outbound call to the email provider (`email_service.send_email()` — a real HTTP request, up to a 10-second timeout for Brevo/SMTP) before responding; a nonexistent email just logged and returned immediately. That's a much larger, more network-variable timing gap than login's fixed bcrypt cost — easily distinguishable, and the dominant signal was response time, not error text. Fixed by extracting the token generation, DB write, and email send into `_dispatch_password_reset_email()`, dispatched via a background daemon thread (same pattern as `services/notification_service.py`'s async Slack dispatch: re-enter the Flask app context and re-query the user by id inside the thread rather than passing the live ORM object across the thread boundary, since SQLAlchemy sessions aren't safe to share across threads) — both branches now return in about the same, fast time regardless of whether an email actually gets sent. `/forgot-password` was already rate-limited (`@limiter.limit("5 per hour")`, matching `/signup`) — no gap there despite an initial mis-read of the decorator order in this file (route decorator first, `@limiter.limit` below it) that looked like a missing limit on first grep. Regression tests in `tests/test_auth.py::TestForgotPasswordTimingSideChannel` (6 tests) assert on the mechanism (background thread dispatched only for existing accounts; the request itself does no DB write; the dispatched closure's own logic — token gen, persistence, email call — verified separately by running it synchronously via a `_ImmediateThread` test double) rather than wall-clock timing; verified 4 of the 6 fail against the pre-fix code (the other 2 test invariants that were already true beforehand, e.g. identical success message, so they're expected to pass either way). **Testing gotcha hit while writing these:** asserting on an ORM object's attributes *after* a nested nested `with flask_app.app_context()` has popped can raise `DetachedInstanceError` or silently return stale identity-mapped data — capture plain values (like `user.id`) before entering the nested context, and call `db.session.expire_all()` before re-querying afterward to force a real re-read instead of trusting a possibly-stale identity map. |
| **SSRF guard didn't validate redirect targets — validated-safe host could 302 straight to a blocked target (FIXED 2026-07-24)** | Flagged in the review above, investigated further: `assert_safe_url()` (`src/utils/network_safety.py`) only validates the URL you hand it — it has zero control over what happens next. Every call site then made the real request separately with `requests`' default `allow_redirects=True` (or, in `run_smoke_test`, explicitly `allow_redirects=True`), so a server that passed validation could 302 straight to `169.254.169.254` (or any other blocked target) and `requests` would silently follow it — redirect-following happens inside urllib3 with zero knowledge of this app's SSRF policy. Affected three different HTTP mechanisms across 7 files: raw `requests` calls (`notification_service.py`'s Slack/Teams webhooks — fully user-supplied, reused repeatedly; `monitoring_tools.py` Prometheus/Grafana; `sonarqube_tools.py`; `nexus_tools.py`; `cicd_tools.py`'s GitLab functions and `run_smoke_test`/`auto_rollback_deployment`; `api_gateway.py`'s outbound platform webhooks via a second, stricter validator `_is_safe_webhook_url`), the `python-jenkins` library's internally-wrapped `requests.Session` (`cicd_tools.py`'s Jenkins functions — no `allow_redirects` param exposed by the library), and native git/libcurl transport (`git_tools.py`'s `git_clone_repository` — `requests` isn't even involved). Most exploitable via `git_clone_repository`/webhook URLs, which are effectively attacker-controlled (a malicious chat user can just ask the agent to clone/notify a domain they own that resolves safely at validation time and 302s on the actual fetch — no DNS-timing tricks needed). Fixed: (1) new `safe_request()` (`network_safety.py`) — a drop-in for `requests.request/get/post/etc.` that validates every hop (initial URL + each `Location` target) via a pluggable `validator` (defaults to `assert_safe_url`; `api_gateway.py` passes an adapter around its stricter `_is_safe_webhook_url` so the redirect fix doesn't silently loosen its policy to allow RFC1918, which `assert_safe_url` deliberately permits for the internal-tool trust model), raises `UnsafeUrlError` instead of following anywhere unvalidated, caps the chain at 5 hops, and strips `Authorization`/`Cookie`/`Proxy-Authorization` (header or `auth=` tuple) on any cross-origin hop so a redirected base_url can't hand a live bearer token/API key to whatever responded with the redirect. All `requests`-based call sites swapped to it. (2) `cicd_tools.py`'s 4 Jenkins client-construction points now call `_disable_jenkins_redirects()`, which monkeypatches the constructed `jenkins.Jenkins` instance's `_session.resolve_redirects` to a no-op — the only lever available since the library exposes no `allow_redirects` param; a Jenkins response is now returned as the raw 3xx rather than silently followed. (3) `git_clone_repository` now passes `multi_options=['-c', 'http.followRedirects=false']` to `Repo.clone_from()` — `-c`/`--config` is normally in GitPython's `unsafe_git_clone_options` blocklist (arbitrary config-injection risk) and needs `allow_unsafe_options=True` to unlock, which is safe here only because the `multi_options` value is fixed and code-controlled, never derived from caller input (the function's only user-influenced kwargs are `branch`/`depth`, not config/upload-pack options). Regression tests: `tests/test_network_safety.py` (+13 tests covering redirect-following to a validated host, blocking a redirect to the metadata endpoint, redirect-chain length capping, cross-origin header/auth stripping, and the custom-validator parameter). **Deliberately not addressed in this pass:** DNS-rebinding (the IP `assert_safe_url` validates vs. the IP `requests`/git actually connects to a moment later) — closing that fully requires pinning the connection to the validated IP (a custom transport adapter), which carries more regression risk (TLS SNI/cert-hostname handling) and doesn't extend cleanly to the git/Jenkins paths; treated as a separate, lower-priority follow-up since it needs attacker-controlled DNS with a short TTL and precise timing, versus the redirect bypass this fix closes which needs nothing but an ordinary 302. |
| **Shared `agent` singleton leaked per-request state across concurrent users (FIXED 2026-07-23)** | Flagged in the review above, investigated further: production runs a single gunicorn worker (`Procfile`: `--worker-class gevent --workers 1 --worker-connections 1000`), so the one `DevOpsAgent` instance (`app.py`'s global `agent`) is shared by every concurrent request in the process, and gevent's cooperative scheduling switches greenlets on every I/O wait — including the entire duration of a Claude/Kimi API call. `process_message_isolated`/`process_message_streaming` (`src/agent/core.py`) stored per-request state (`conversation`, `pending_download`, `_current_user_id`, `_tools_override`, `_trust_tool_results`, `_sandbox_mode`, `_current_conversation_id`, `_pending_approval`, `_last_tools_used`) as **plain instance attributes** with no real isolation — a declared `self._conversation_lock = threading.Lock()` was never acquired anywhere in the file. Concretely, if user A's request yielded on an Anthropic API call while user B's request ran on the same shared object, B's writes to any of those attributes were visible to (and could be overwritten by) A's request when it resumed — worst case, `_sandbox_mode` is read directly to gate real-vs-mocked tool execution (`core.py` ~lines 1360-1762), so a user running a "simulate deleting this RDS instance" sandbox request could have that flag flipped to `False` by an unrelated concurrent real request and have the delete **execute for real** against their own (correctly-isolated) credentials, with zero warning. Also possible: cross-user conversation-history leakage (`self.conversation` reassigned wholesale), wrong-user audit/tool-usage attribution (the `_current_user_id`/`_last_tools_used` race originally flagged), and misdelivered keypair/file downloads (`self.pending_download`). Fixed by converting all nine fields to `@property` descriptors backed by `self._local = threading.local()` (`_greenlet_local_property()` in `core.py`) instead of plain instance attributes — gunicorn's gevent worker monkey-patches `threading.local` to be greenlet-local, the same mechanism already relied on for per-user AWS/Azure/GCP credential isolation (`_set_cloud_user_context`), so this required zero changes to any of the dozens of existing `self.attr` read/write call sites; only `__init__` (create `self._local` before first use) and the dead lock declaration changed. Mutable defaults (`_last_tools_used`) use a `default_factory` so an unset thread/greenlet gets its own fresh list rather than a shared one it could contaminate by appending in place. Regression tests: `tests/test_agent_request_isolation.py` (5 tests using real OS threads + `threading.Event` handoffs to force deterministic interleaving; verified they fail against the pre-fix code — including reproducing the sandbox-bypass scenario exactly). **Lesson:** any object shared across requests under a gevent (or other cooperative-concurrency) worker needs per-request state to live in `threading.local()`-backed storage, not instance attributes — a "save original, restore in `finally`" pattern looks like proper isolation but does nothing to stop a *different* concurrent request from reading or overwriting the value while the first is waiting on I/O, which is the majority of any request's wall-clock time when it calls an LLM API. |

## Verification Commands

```bash
# Check tool counts per module
python -c "from src.tools.aws_tools import get_tools; print(f'AWS: {len(get_tools())}')"
python -c "from src.tools.kubernetes_tools import get_tools; print(f'K8s: {len(get_tools())}')"
python -c "from src.tools.azure_tools import get_tools; print(f'Azure: {len(get_tools())}')"
python -c "from src.tools.gcp_tools import get_tools; print(f'GCP: {len(get_tools())}')"

# Find unregistered functions in a module (replace aws_tools with target module)
python -c "
import re
content = open('src/tools/aws_tools.py').read()
defined = set(m.group(1) for m in re.finditer(r'^def ([a-z]\w+)\(', content, re.M)
              if not m.group(1).startswith('_') and m.group(1) != 'get_tools')
from src.tools.aws_tools import get_tools
registered = set(t['name'] for t in get_tools())
print('Unregistered:', defined - registered)
"

# Verify all handlers are callable and schemas present
python -c "
from src.tools import aws_tools, kubernetes_tools, azure_tools, gcp_tools
for name, mod in [('AWS', aws_tools), ('K8s', kubernetes_tools), ('Azure', azure_tools), ('GCP', gcp_tools)]:
    tools = mod.get_tools()
    for t in tools:
        assert callable(t['handler']), f'{t[\"name\"]} handler not callable'
        assert 'input_schema' in t, f'{t[\"name\"]} missing schema'
    print(f'{name}: {len(tools)} tools OK')
"
```

## 2026-07-16: Health score 500s + Skills feature inert in production

**Symptoms:** `/api/dashboard/health-score` returned 500 for every user
("type object 'CostOptimization' has no attribute 'estimated_savings'");
`/api/onboarding/scan` crashed at the savings step; the Skills page showed
the empty state for all prod users and trigger-based skill injection never
fired.

**Root causes (two independent bugs found by a Playwright functional audit):**
1. Four query sites referenced `CostOptimization.estimated_savings` and two
   referenced `.detected_at` — the real columns are
   `potential_monthly_savings` and `created_at`. Crash sites: health_score.py,
   app.py onboarding scan, scheduler.py cost-scan + weekly-summary tasks.
2. Built-in skills were loaded only inside app.py's `if __name__ == '__main__'`
   block — production runs `gunicorn app:app`, which never executes it. On top,
   no caller ever passed `app` to `get_skills_engine()`, so the engine's
   list/context methods short-circuited to empty even when skills were loaded.

**Fix:** renamed the attribute references; moved skills loading to module
import time with `get_skills_engine(app)`. Regression-guarded in
`tests/test_functional_regressions.py` (guards include asserting the invalid
attribute names don't exist on the model).

**Lesson:** SQLAlchemy attribute errors on models only explode at request
time, not import time — endpoint smoke tests (status 200 for a logged-in
user) catch this class cheaply. Anything registered only in `__main__` is
invisible to gunicorn.

## 2026-07-17: Stripe key rotation didn't take effect — config/.env overrode Secrets Manager

**Symptoms:** After rotating the Stripe API key and updating AWS Secrets
Manager (`devops-agent/production`), payments stayed broken. No Stripe errors
in logs; the app was silently using the old revoked key.

**Root causes (three stacked):**
1. `stripe_integration.py` read `config/.env` on the server FIRST and only
   fell back to os.environ — the server's `config/.env` (untouched since
   June 12) still held the old key and won over Secrets Manager. Prefix
   comparison is useless here: `sk_live_51<account>` prefixes are identical
   for every key in the account — compare sha256 hashes instead.
2. The EC2 instance role (`devops-agent-ssm-role`) had no
   `secretsmanager:GetSecretValue` — so `init_secrets()` had never actually
   loaded Secrets Manager in production. Fixed with an inline policy scoped
   to the one secret ARN.
3. The AWS access key stored in GitHub Actions secrets had been deactivated
   during the same key-rotation session, breaking all deploys
   ("security token invalid"). Updated `AWS_ACCESS_KEY_ID` /
   `AWS_SECRET_ACCESS_KEY` repo secrets.

**Fixes:**
- Server `config/.env` STRIPE_* values rewritten from Secrets Manager
  on-instance (via venv boto3 + instance role — secret values must never go
  through SSM command parameters; they land in CloudTrail).
- Precedence inverted in `stripe_integration.py`: os.environ (Secrets
  Manager) now wins; `config/.env` is the local-dev fallback. Guarded by
  `tests/test_stripe_precedence.py`.

**Quarterly Stripe rotation procedure (single source of truth = Secrets Manager):**
1. In the Stripe dashboard, create/roll the key. Note: standard secret keys
   do NOT auto-expire; only set an expiration on restricted keys if you
   explicitly want one. Rolling a key lets you choose when the old one dies —
   pick a window long enough to complete this procedure.
2. Update `STRIPE_SECRET_KEY` (and only what changed) in the
   `devops-agent/production` secret in AWS Secrets Manager.
3. Restart the app (redeploy, or `sudo systemctl restart devops-agent` via
   SSM) — `init_secrets()` loads the new values at startup.
4. Verify: run a test checkout end-to-end including webhook credit grant.
5. Only then let the old key expire / delete it.
6. If rotating AWS keys at the same time: update the GitHub Actions
   `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` secrets BEFORE deactivating
   the old key, or deploys break.

---

## Scheduler retry-storm + DB backups never ran in prod (2026-07-20)

**Symptom:** After #71 made the background scheduler run under gunicorn, the DB
backup task started firing every ~30s and logged 645 errors:
`OSError: [Errno 30] Read-only file system: '/backups'`. No database backups
existed. (Postgres runs *locally* on the EC2 instance, so this was a real
data-loss exposure — instance death = DB gone.)

**Two root causes:**
1. `_run_db_backup()` defaulted `BACKUP_DIR` to `/backups` (not writable by the
   `ubuntu` service user) and called `os.makedirs()` *before* its try block, so
   the failure propagated out of the function.
2. `_scheduler_loop()` only advanced `last_run[task]` on success. A task that
   raised kept `last_run` at `datetime.min`, so `now - last_run >= interval` was
   always true → the failing task retried on every 30s tick instead of backing
   off to its interval. (Same shape as the monitoring_tick json bug, which also
   fired every 30s.)

**Fixes (code, `services/scheduler.py`):**
- Advance `last_run[task] = now` *before* running the task, so a raising task
  backs off to its full interval. Guarded by `tests/test_scheduler_retry_backoff.py`.
- Moved `os.makedirs(backup_dir)` inside `_run_db_backup`'s try so a bad dir is
  logged, not propagated.

**Fixes (prod ops, one-time):**
- Created writable `/var/www/devops-agent/backups` (owned by `ubuntu`).
- Created hardened S3 bucket `s3://devopsagent-db-backups` (us-east-1): public
  access blocked, SSE-S3 default encryption, lifecycle expiring
  `database-backups/` objects after 35 days.
- Attached least-privilege inline policy `devops-agent-db-backup-s3` to role
  `devops-agent-ssm-role` (PutObject/GetObject on `database-backups/*` +
  scoped ListBucket).
- Set `BACKUP_DIR` + `BACKUP_S3_BUCKET` in the root `.env`
  (`/var/www/devops-agent/.env`) and restarted the service.
- Verified: manual backup produces a local `.gz` and uploads to S3; error storm
  stopped. pg_dump 14.23 matches local server 14.23.

---

## Two non-blocker bug fixes: compliance run-check + AI Templates feature (2026-07-20)

Found during the pre-launch end-to-end audit.

### `/compliance/api/run-check` 500'd for every input
The route (`routes/compliance.py`) passed `request.json.get('framework_id')`
(None when omitted) straight into `run_compliance_check -> enable_framework ->
None.upper()`. Even a valid framework 500'd because the route did
`jsonify(result)` on a `ComplianceReport` model instance (not serializable). No
UI referenced the endpoint, so it had never worked. Fixed: validate framework_id
(400 for missing/unsupported, against `('soc2','hipaa','pci_dss')`), serialize
via `report.to_dict()`, and guard `enable_framework` against a falsy name.
Guarded by `tests/test_compliance_run_check.py`.

### AI Infrastructure Templates was non-functional scaffolding
The feature only *looked* fine because no template had ever existed. Bugs fixed:
- `create_template()` wrote to a `specification=` column that doesn't exist
  (model has `template_content` + `variables`).
- `api_templates` read `t.provider` / `t.complexity` / `t.estimated_cost` — none
  are model attributes; it would 500 the moment any template existed. It also
  only returned the user's own templates, never public ones.
- `preview_template()` was called by a route but did not exist in the service.
- The "Use Template" button called an **undefined** `useTemplate()`.
- No starter catalog was ever seeded.

Rebuilt around a single canonical serialization (`AIInfrastructureService.
template_to_dict`) used by the API, the grid, and the detail page, so model
column names never leak as mismatched attributes again. Added
`services/starter_templates.py` (6 curated public Terraform templates) +
`seed_public_templates()` (idempotent, owned by a `system@devopsagent.io` user,
seeded at startup like skills — the __main__ block never runs under gunicorn).
New: `get_visible_templates`, `preview_template` (substitutes only declared
`${var}` tokens, leaving Terraform's own `${...}` intact), `clone_template`, and
a `/ai/api/templates/<id>/clone` endpoint. Rewrote `templates.html` (starter/
your sections, working `useTemplate`) and `template_detail.html` (variables +
live preview + copy + save). Guarded by `tests/test_ai_infrastructure_templates.py`.

**Test-isolation note:** the suite uses a session-scoped shared in-memory SQLite;
tests that commit rows tied to `test_user` (compliance frameworks, infra
templates) MUST delete those child rows in a fixture that finalizes *before* the
user fixture — else deleting the user nulls a NOT NULL FK and poisons the session
for the rest of the suite (same trap documented in `test_template_isolation.py`).

## Scheduled monitoring check found an untracked gevent CVE hiding behind `continue-on-error` (FIXED 2026-07-20)

A routine automated health-check pass (not a push/PR-triggered CI run) inspected
the daily `security-scan.yml` results and found the job reporting `success`
while `safety check` had actually flagged `gevent==24.11.1` (Safety DB ID
**76839** / **PVE-2025-76839**: HTTP request smuggling in pywsgi, fixed in
`>=25.4.2`). The job stayed green because every security-scan step is
`continue-on-error` by design (see CI / Security Scanning section) — a real,
unignored finding can pass silently indefinitely unless someone reads the logs.
`pip-audit` did not catch this one (different advisory source than `safety`),
which is why both tools run. Fixed by pinning the exact fixed release,
`gevent==25.4.2`, with the advisory ID in a trailing comment per the
Dependency Pinning Policy. **Lesson:** `continue-on-error` on the security job
means CI green is not proof of a clean scan — treat the scheduled scan logs
(or the `scheduled-bandit-report` artifact) as something that needs an
occasional human/agent read, not just a status-check glance.

---

## rotate_api_key ownership hardening (2026-07-23)

Post-#80 IDOR sweep found `APIGatewayService.rotate_api_key(key_id)` shared the
webhook bug's shape: no `user_id` (no ownership enforcement) and it called the
now-2-arg `revoke_api_key(key_id)` with one arg (would crash). It was dead code
(no route/caller), so not exploitable — hardened defensively: added an optional
`user_id` owner check and fixed the revoke call to pass the owner.
Guarded by `tests/test_api_key_rotate_ownership.py`.

---

## Scheduled audit: 5 confirmed vulnerabilities across concurrency, timing, SSRF, and IDOR (2026-07-24)

A routine scheduled review (parallel agents each auditing routes/, services/,
src/tools/+safety.py, src/agent/, and code smells/duplication) found and fixed
five real, independently-confirmed bugs. None were caught by the daily
`security-scan.yml` cron (pip-audit/safety/bandit) — all five needed semantic
understanding of the app's own invariants, not a dependency-CVE or lint scan.

1. **`_tool_event_callback` cross-request leak (`src/agent/core.py`).** Every
   other per-request field on `DevOpsAgent` was converted to a
   `_greenlet_local_property` after the agent-singleton race fix (see below),
   but this one — the SSE tool-start/tool-done callback `app.py`'s streaming
   route installs for the whole tool loop (up to 50 iterations, each with a
   long I/O-yielding Claude/Kimi call) — was added as a plain instance
   attribute and never migrated. On the single gevent worker, a second
   concurrent request's `set_tool_event_callback()` could overwrite the first
   request's callback mid-loop, delivering one user's tool_start/tool_done
   events (and the `ChatMessage.tool_trace` built from them) to a different
   user's stream. Fixed by adding it to the `_greenlet_local_property` list.
   Guarded by `test_tool_event_callback_isolated_across_threads` in
   `tests/test_agent_request_isolation.py`.

2. **`routes/mcp.py` OAuth login reopened the login-timing side channel.** The
   MCP connector's own login form (`oauth_authorize()`) implemented an
   independent `if not user or not user.check_password(password)` check —
   `or` short-circuits, so an unknown email skips bcrypt entirely while a
   wrong password on a real account pays bcrypt's cost, making account
   existence distinguishable by response time. This is the exact bug
   `_run_timing_safe_password_check()` was built to close in the main `/login`
   route (PR #86) — the MCP route just never got wired to it. Fixed by
   importing and calling the shared helper. Guarded by
   `TestOAuthAuthorizeLoginTimingSideChannel` in `tests/test_mcp_oauth.py`.

3. **`trigger_sonar_analysis` and `ansible_vault_encrypt` were unclassified
   (silently low-risk, no confirmation prompt).** Same shape as prior
   `provider_verb_noun` gaps: `trigger_sonar_analysis`'s prefix isn't in the
   medium-risk auto-detect list even though its sibling triggers
   (`trigger_jenkins_job`, `trigger_github_workflow`,
   `create_gitlab_pipeline_trigger`) are; `ansible_vault_encrypt` mutates a
   file in place like its already-medium `ansible_vault_decrypt`/
   `ansible_vault_view` siblings. Added both to `medium_risk_tools`. Guarded
   by new tests in `tests/test_new_tools.py`.

4. **`services/sso_service.py` SSRF gap — org-admin-controlled OIDC endpoints
   fetched with raw `requests`, bypassing the SSRF guard.** `_discover()`,
   `_exchange_code()`, `_validate_id_token()`, and `_fetch_userinfo()` all
   called `requests.get`/`requests.post` directly on a `metadata_url` an org
   owner sets via `routes/organizations.py`'s `sso_settings` (gated only by
   `@org_admin_required`) and on the `token_endpoint`/`jwks_uri`/
   `userinfo_endpoint` the resulting discovery document supplies — none of it
   went through `assert_safe_url()`/`safe_request()`, unlike every other
   caller-supplied-URL tool in the app. An org owner could point
   `metadata_url` at the cloud metadata endpoint or an internal service, and
   it would be fetched server-side on every login attempt. Fixed by routing
   all four functions through `safe_request()`, catching `UnsafeUrlError` and
   re-raising as `SSOError` (routes catch `SSOError` specifically, not
   `ValueError`, so the raw exception type would have 500'd instead of
   showing the generic login-failure message). Updating this broke
   `tests/test_sso.py`'s existing mocks (they patched `requests.get`/`.post`
   directly, which `safe_request()` doesn't call) — fixed by monkeypatching
   `sso_service.safe_request` instead.

5. **`services/approval_service.py._execute_tool()` never set the requester's
   cloud credential context.** Unlike `process_message_isolated`/
   `process_message_streaming` (which always call
   `agent._set_cloud_user_context(user_id)` before running a tool), the
   approve-and-execute path called `agent.tools[tool_name](**...)` directly.
   Since `aws_tools._get_boto_client` hard-requires a user context, approving
   an AWS action either failed closed with "Authentication required"
   (silently no-opping a safety-critical action the requester thought had
   run) or could run under whatever context a previous request left on the
   greenlet. Fixed by setting `req.requester_id` as the context before the
   tool call and clearing it in a `finally`. Guarded by
   `tests/test_approval_credential_context.py`.

**Also hardened defensively (not independently exploitable today):**
`APIGatewayService.update_webhook()` was the one webhook method missing the
`user_id` ownership check its siblings (`delete_webhook`, `toggle_webhook`,
`test_webhook`) already had — same shape as the `rotate_api_key` fix above.
Currently dead code (no route calls it), but hardened before it becomes live.
Guarded by `tests/test_webhook_update_ownership.py`.

**Not fixed — noted for a future pass, lower priority / higher risk to change
under a routine audit:** `services/websocket_service.py` (428 lines) has zero
call sites; `services/incident_response.py`'s `_handle_kubernetes_action`/
`_handle_aws_action` repeat a 4-5-branch dispatch pattern that could collapse
into one helper; `app.py`'s `api_chat`/`api_chat_stream` (461/618 lines) mix
several concerns and duplicate guardrail/attachment logic between the
streaming and non-streaming paths; `src/agent/core.py`'s Kimi streaming vs.
non-streaming tool-handling is copy-pasted rather than shared (the Claude
paths share `_handle_tool_uses`, Kimi's two paths don't); `routes/changes.py`'s
`_user_active_org_ids()` duplicates `MultiTenancyService.get_user_organizations()`
instead of calling it.

---

## SSRF and login-timing bugs kept recurring in new locations — added a structural check instead of another one-off fix (2026-07-24)

By this point SSRF gaps and login-timing side channels had each been found
and fixed **independently, in a different file, on four separate occasions**
(curriculum/notification/git_tools/api_gateway → the redirect-following gap
across 7 more files → `services/sso_service.py` → `routes/mcp.py`'s OAuth
login form). None of these were the same bug regressing — each was a
*different* piece of code that either never got the guard in the first
place or reimplemented its own copy of the logic instead of calling the
shared helper. The guard (`assert_safe_url`/`safe_request`) and the shared
timing-safe password check are both **opt-in per call site** — nothing
structurally stops a new integration, or an old one nobody's checked yet,
from skipping them.

**While cataloging every remaining raw `requests.*` call site to build the
checker below (see next paragraph), found a fifth, previously-undiscovered
instance:** `app.py`'s `POST /api/notification-channels/<id>/test` made a
raw `requests.post(channel.webhook_url, ...)` call with **zero** SSRF
validation and echoed the **full, untruncated** response body back to the
caller in the JSON error field — an SSRF + unbounded-response-oracle combo
worse than the `api_gateway.py test_webhook()` bug fixed earlier (that one
was capped at 500 chars). `channel.webhook_url` is user-configured
(`UserNotificationChannel`, same field `notification_service.py`'s
`SlackClient.send_webhook` already protects) and reachable by any
authenticated user testing their own channel — confirmed live by writing a
regression test against the *pre-fix* code: it didn't return an error, it
actually spent the full 10-second timeout trying to connect to
`169.254.169.254` before failing on this sandbox's lack of route to it. On a
real AWS EC2 instance that connection would have succeeded and returned live
IAM credentials. Fixed by routing through `safe_request()` and truncating the
echoed body to 500 chars, matching every other webhook-test endpoint.
Regression tests: `tests/test_notification_channel_test_ssrf.py`.

**The actual fix — `scripts/check_security_invariants.py` — a structural
check instead of another one-off patch.** An AST-based scanner run as part of
the pytest suite (`tests/test_security_invariants.py`, so it's already gated
by `ci.yml`'s `test` job with zero workflow changes needed) that fails the
build if either pattern reappears:

1. A raw `requests.get/post/put/patch/delete/request(...)` call (handles
   import aliases, e.g. `import requests as http_requests`) anywhere in
   `src/tools/`, `services/`, `routes/`, `api/`, or `app.py`, outside
   `src/utils/network_safety.py` itself.
2. A direct `.check_password(...)` call anywhere in those same locations
   outside `routes/auth.py`.

Cataloged and exempted every genuinely safe existing call site with an
inline `# ssrf-safe: <reason>` comment (37 of them — Datadog/PagerDuty/
OpsGenie/GitHub's own hardcoded API hosts, Brevo/SendGrid, a
geolocation API where only the URL *path* is caller-supplied, and
`services/proactive_monitoring.py`'s Prometheus/Datadog collectors, which
read from an env var / a `config` dict that's never actually populated by
any real instantiation today) — each with a reviewed, specific reason, not a
blanket bypass. Verified the checker actually works by injecting a fake
violation into a real scanned file and confirming it's caught, then
reverting. Unit-tested the detection logic itself against synthetic source
(`tests/test_check_security_invariants.py`) — including the exact
false-positive shape that would otherwise trip a naive grep-based version:
`container.resources.requests.get('cpu')` (a Kubernetes resource dict
`.get()`, unrelated to the `requests` HTTP library) is correctly ignored
because the AST check requires the call's base to resolve to an actual
`import requests` binding, not just contain the substring `requests`.

**Why a test instead of a CI workflow step:** it runs identically locally
(`pytest`) and in CI, needs no `ci.yml` changes, and can't be silently
skipped the way a `continue-on-error` step (like this same file's
`security` job) can. **Why not just document the convention harder:** that's
what CLAUDE.md's SSRF section and login-timing note already did, and it kept
getting missed anyway — a structural check doesn't rely on anyone (human or
agent) remembering to check the docs. **Lesson:** when the *same review
finding* the same shape of gap in a new place three-plus times in one
project history, that is itself a signal to stop fixing instances and go
build the guardrail; see CLAUDE.md's "Security invariants" section for how
to add a new check or exemption.

---

## Scheduled audit: org role-escalation, unauthenticated Teams bot endpoint, webhook SSRF gap, GCP credential leak (2026-07-25)

A routine scheduled review (parallel agents auditing `routes/`+`api/`,
`services/`, and `src/tools/`+`src/agent/`) found and fixed four issues, none
of which were the SSRF/login-timing shape already covered by
`scripts/check_security_invariants.py` — a reminder that the structural
checker only closes the two specific patterns it scans for, not every
security bug shape.

1. **Org `admin` could self-promote to `owner` (`routes/organizations.py`
   `update_member_role`).** The route took `role = request.form.get('role')`
   and passed it straight to `MultiTenancyService.update_member_role()`
   (`services/multi_tenancy.py`), which just sets `member.role = new_role` and
   commits — no allow-list, no check that the caller was already an `owner`.
   The route is gated only by `@org_admin_required`, which accepts both
   `'owner'` and `'admin'`. Since `'owner'` is the only role with owner-only
   powers (org deletion/billing, gated via
   `user_has_org_permission(..., ['owner'])`), any org `admin` could
   `POST /organizations/<org_id>/members/<own_user_id>/role` with
   `role=owner` and grant themselves full ownership — a straightforward
   vertical privilege escalation within a tenant. Fixed by validating
   `new_role` against the known role set (`owner`/`admin`/`member`/
   `billing`/`viewer`) and requiring the caller to already be an `owner`
   before granting or changing `owner` access. Regression tests:
   `tests/test_org_role_escalation.py`.

2. **Microsoft Teams ChatOps endpoints had zero authentication
   (`routes/chatops.py`).** `teams_messages`/`teams_commands` had no
   `@login_required` and — unlike the Slack endpoints, which verify an HMAC
   signature when `SLACK_SIGNING_SECRET` is set — performed no verification
   of the caller at all, despite the ChatOps dashboard UI instructing admins
   to set `TEAMS_APP_ID`/`TEAMS_APP_PASSWORD` for exactly this purpose; those
   env vars were never actually read anywhere in the code. Any anonymous POST
   with a crafted Bot Framework-shaped body was processed as a legitimate
   Teams message and dispatched into `ChatOpsService.process_message()`.
   Fixed by validating the inbound Bot Framework JWT
   (`Authorization: Bearer <token>`) against Microsoft's JWKS
   (`https://login.botframework.com/v1/.well-known/openidconfiguration`),
   checking `iss`/`aud` (against `TEAMS_APP_ID`)/`exp` via `joserfc` — the
   same JWT/JWKS validation pattern already used for OIDC SSO in
   `services/sso_service.py._validate_id_token()`. The endpoint now fails
   closed (401) if `TEAMS_APP_ID` isn't configured at all, rather than
   accepting unauthenticated traffic when the integration is unset up.
   Regression tests: `tests/test_chatops_teams_auth.py`. **Separately noted,
   not fixed (low severity, pre-existing dead code):** `ChatOpsService`'s
   `_cmd_status`/`_cmd_incident_detail`/`_cmd_acknowledge`/`_cmd_resolve` call
   `IncidentResponseEngine` methods positionally without the required leading
   `user_id` argument, so every one of those commands raises `TypeError`,
   silently swallowed by `process_message()`'s generic `except Exception`.
   These have apparently never worked since the incident engine moved to
   per-user isolation, and there's no existing design for mapping a Slack/
   Teams identity to an app `user_id` — real access-control design work, not
   a one-line signature fix, so left for a future pass.

3. **Slack/Teams notification webhooks could reach internal RFC1918 hosts
   (`services/notification_service.py`, `app.py`).** `SlackClient.send_webhook`/
   `TeamsClient.send`, and `app.py`'s `POST /api/notification-channels/<id>/test`
   route, validated the user-supplied `webhook_url` with `assert_safe_url()`/
   `safe_request()`'s default validator — which only blocks loopback/
   link-local/multicast by design, since most callers of that default (Jenkins/
   SonarQube/Nexus/Prometheus) are self-hosted internal tools that legitimately
   live on private IPs. But a notification webhook is a different trust
   model: an arbitrary user-configured *external* endpoint, exactly like
   `services/api_gateway.py`'s outbound platform webhooks, which already had a
   stricter validator (`_is_safe_webhook_url`/`_raise_if_unsafe_webhook_url`,
   blocking RFC1918/reserved ranges too) for this exact reason — it just
   was never reused by the Slack/Teams code. Any user could set their Slack
   webhook URL to `http://10.x.x.x/...` and every subsequent alert/incident
   notification would POST to that internal address — blind SSRF into the
   app's own network. Fixed by moving the stricter check into
   `src/utils/network_safety.py` as a shared
   `assert_safe_external_webhook_url()`, having `api_gateway.py`'s two
   functions delegate to it (removing the duplicated ipaddress/socket logic),
   and wiring `notification_service.py`'s Slack/Teams clients plus `app.py`'s
   notification-channel-test route to use it as their `validator=`. Regression
   tests added to `tests/test_network_safety.py`.

4. **GCP service-account private key left on disk when credential loading
   failed (`services/credential_service.py` callers).**
   `get_user_gcp_credentials_file()` writes the decrypted service-account JSON
   (including the RSA private key) to a `tempfile.mkstemp()` path; all four
   callers (`src/tools/gcp_tools.py._get_user_gcp_credentials`,
   `services/infrastructure_sync.py`'s `sync_gcp_compute_instances`/
   `sync_gcp_storage_buckets`/`sync_gcp_sql_instances`) only deleted that file
   *after* successfully constructing
   `service_account.Credentials.from_service_account_file(creds_path)`, with
   no `try/finally`. A malformed/invalid/revoked key left the plaintext
   private key on disk indefinitely — worse under repeated failed sync
   attempts, since each one leaks another file into the shared temp
   directory. Fixed by wrapping the `from_service_account_file(...)` call in
   `try/finally: os.remove(creds_path)` at all four call sites. Regression
   tests: `tests/test_gcp_credentials_file_cleanup.py`.

**Also verified clean in this pass:** `scripts/check_security_invariants.py`
reports zero violations after all the above edits.

---

## Cloudflare 524 on long /api/chat turns — connection idle-timeout mismatch, not a backend failure (2026-07-30)

A user reported a 524 ("A Timeout Occurred") from Cloudflare when asking the
agent to perform a task. Confirmed live via server logs: nginx recorded a
`499` (client — effectively Cloudflare — disconnected) for a `POST /api/chat`,
and gunicorn's own access log shows that *same* request completing
successfully (`200`) about 25 seconds later — the backend was never broken,
it just finished after Cloudflare had already given up and shown the user an
error.

**Root cause:** `/api/chat` sent zero response bytes to the client until the
entire agent turn was done. Kimi-tier "swarm" tasks are explicitly designed
to take up to ~290s (the frontend gives itself a 290s client-side abort
timeout to match gunicorn's own 300s worker timeout — see the comment
`// Kimi uses the non-streaming endpoint — swarm scales with task
complexity` in `templates/index.html`). Cloudflare's edge proxy has its own
~100s idle-connection timeout that can't be raised below Enterprise tier, so
any turn longer than ~100s got killed by Cloudflare regardless of how
patient our own gunicorn/frontend timeouts were.

**Also found while diagnosing this:** production's actual gunicorn config
(the `devops-agent` systemd unit: `--workers 3` with the *default* `sync`
worker class) doesn't match the repo's `Procfile` (`--worker-class gevent
--workers 1 --worker-connections 1000`) — the Procfile appears to be stale/
aspirational documentation for a different deploy target, not what's
actually running. Doesn't change any conclusions from the earlier
concurrency-race fix (`threading.local()`-backed properties are correct and
harmless either way — sync workers are separate OS processes with no
shared-memory race to begin with), but worth reconciling at some point so
the docs match reality.

**Fix:** `api_chat()`'s actual `agent.process_message_isolated()` /
`_process_free_tier_chat()` call now runs in a background thread while the
view streams a single whitespace byte every `CHAT_KEEPALIVE_INTERVAL_SECONDS`
(15s) back to the client for as long as the thread is still alive — keeping
Cloudflare's connection looking active without changing anything about the
actual turn's logic or duration. The rest of the original synchronous code
(usage logging, sanitization, saving the assistant message, credit
deduction, building `response_data`) is unchanged, just now living inside
the streaming generator (wrapped in `flask.stream_with_context` so
`current_user`/`db.session`/etc. all keep working exactly as before) instead
of directly in the view function body. The frontend needed **no changes at
all**: `response.json()` (and Python's `json.loads()`) both ignore
insignificant leading whitespace around a JSON value per spec, so a few
keep-alive bytes before the real payload are completely transparent to the
existing `const data = await kimiResp.json()` call.

One behavioral note: once the response starts streaming, the HTTP status is
already committed to 200 — an exception in the post-agent-call code (usage
logging, DB writes, etc.) can no longer become a 500 the way the old
synchronous handler could. Added a dedicated `try/except` inside the
generator for this narrow window that rolls back the session and yields a
best-effort `{"error": ...}` body instead of dropping the connection; the
agent-call's own exception handling (already converting failures into a
plain "Error processing request: ..." response string) is unchanged.

Regression tests: `tests/test_chat_keepalive.py` — a mocked slow agent call
proves real keep-alive whitespace bytes are sent and the final JSON still
parses correctly (verified this fails without the fix); a mocked fast call,
an error-raising call, and a credit-deduction/message-persistence check all
confirm no regression to the common paths. Also verified live against the
actual local dev server (not just Flask's test client) — full login + 2FA +
`/api/chat` round trip, correct credit deduction, valid JSON response.

**Lesson:** a 502/524/timeout from the client's perspective doesn't always
mean the backend crashed or hung — check whether the backend actually
*finished* shortly after the client gave up before assuming it's a hard
failure. A proxy layer's own idle-timeout, invisible from the application's
logs alone, can silently cap how long a legitimately-designed-to-be-slow
endpoint is allowed to run.

---

## Scheduled audit: live-verified git RCE, two credential-isolation bypasses, secret exfiltration, container-escape, and two IDORs (2026-08-04)

A routine scheduled review (four parallel agents auditing `src/tools/`+
`safety.py`, `routes/`+`api/`, `services/`, and recent commits/core modules)
found and fixed eight real, independently-confirmed issues. The most severe
was **live-verified** by the reviewing agent actually running the exploit
against a scratch repo before reporting it, not just read from the code.

1. **`git_grep_search` flag-injection RCE (`src/tools/git_tools.py`).** The
   `_reject_flag_like()` guard added 2026-07-27 for `git_pull`/`git_push`/etc.
   was never extended to four functions added later that pass a caller-supplied
   value as a bare positional arg to `repo.git.*`: `git_grep_search`'s
   `pattern` (`git grep --open-files-in-pager=<cmd>` execs the given pager —
   confirmed live: `pattern="--open-files-in-pager=touch /tmp/pwned #"`
   created the file), `get_diff`/`git_diff_stat`'s `commit1`/`commit2` and
   `git_show_file_at_commit`'s `commit_sha` (`git diff/show --output=<file>`
   writes command output to an arbitrary path — arbitrary file write,
   confirmed live), and `git_blame_file`'s `file_path` (`git blame
   --contents=<file>` echoes an arbitrary file's contents back in the
   response — arbitrary file read, e.g. `file_path="--contents=/etc/passwd"`,
   confirmed live). None of the five were in `safety.py`'s risk sets either,
   so all fired with zero confirmation prompt. Fixed by extending
   `_reject_flag_like()` to all five params and adding all five tool names to
   `medium_risk_tools` as defense-in-depth. Regression tests added to
   `tests/test_git_tools_argument_injection.py` (8 new cases).

2. **`generate_eks_kubeconfig` bypassed per-user AWS credential isolation
   (`src/tools/aws_tools.py`).** Instead of `_get_boto_client()` — whose
   entire purpose, per its own docstring, is to never fall back to
   environment/IAM-role credentials — this function shelled out to
   `aws eks update-kubeconfig --dry-run`, which resolves credentials via the
   AWS CLI's own default chain (the host's env vars / IAM instance role), not
   this app's per-user thread-local context. It only fell back to the safe
   boto3 path if the CLI call *failed*. On the documented EC2 deployment, any
   authenticated user — regardless of their own linked AWS account — could
   call this tool with an arbitrary `cluster_name` and have it queried using
   the **platform host's own AWS identity**. Fixed by removing the CLI
   shell-out entirely and always building the kubeconfig via
   `_get_boto_client('eks', region)`.

3. **All 5 GCP Secret Manager tools bypassed per-user GCP credential isolation
   (`src/tools/gcp_tools.py`).** `_get_gcp_client()` builds every other GCP
   service client with the requester's per-user credentials when available,
   but Secret Manager was never added to it — `list_secrets`, `get_secret_value`,
   `create_gcp_secret`, `delete_gcp_secret`, and `add_secret_version` all
   called `secretmanager.SecretManagerServiceClient()` directly with no
   credentials argument, which falls back to Application Default Credentials
   (the host's own service account). Any authenticated user could list and
   read secrets from the **platform's own GCP project**, not their own — worse
   than finding #2 above since it's live secret material, not just cluster
   metadata. Fixed with a new `_get_secretmanager_client()` helper (mirrors
   `_get_gcp_client`'s per-user-credentials pattern) used at all 5 call sites.
   Separately, `get_secret_value` returned decrypted secret plaintext directly
   into the tool result — the chat/tool_trace/LLM-provider path — which no
   other secret-bearing tool in this codebase does (AWS deliberately has no
   `secretsmanager:GetSecretValue`/`ssm:GetParameter WithDecryption`
   equivalent; `list_github_secrets` never exposes values). Escalated to
   `high_risk_tools` as defense-in-depth; the credential-isolation fix is the
   real fix.

4. **Ansible module allowlist permitted two command-execution-equivalent
   modules (`src/tools/ansible_tools.py`).** `_ALLOWED_ANSIBLE_MODULES`'
   stated purpose is blocking modules that run arbitrary OS commands on
   remote hosts (`shell`/`command`/`raw`/`script` excluded), but it allowed
   `cron` (`job=` accepts an arbitrary shell command line — functionally
   identical to `shell`) and `authorized_key` (injects an attacker-controlled
   SSH public key onto the target for persistent backdoor access). Removed
   both from the allowlist. `ansible_adhoc_command` was already high-risk in
   `safety.py`, so this closes a gap the confirmation prompt alone didn't.

5. **`docker_create_container` allowed unrestricted host bind-mounts
   (`src/tools/docker_tools.py`).** The `volumes` parameter was passed to
   `client.containers.run()` with no validation of host source paths —
   mounting `/var/run/docker.sock` or `/` gives trivial container-escape to
   full host/Docker-daemon control, the same risk class as `execute_command`,
   yet the tool was only medium-risk (same tier as `docker_push_image`).
   Fixed with `_validate_container_volumes()` blocking the clearest cases
   (docker socket, `/`, `/root`, `/etc`, `/boot`, `/proc`, `/sys`) and
   escalating the tool to `high_risk_tools`. Regression test added to
   `tests/test_new_tools.py` (updated from `..._is_medium_risk` to
   `..._is_high_risk`).

6. **`routes/organizations.py` `view_team` IDOR.** Computed `membership =
   service.get_membership(...)` but — unlike the sibling `list_teams`, which
   redirects non-members away — never checked it before rendering. Any
   `@login_required` user who knew or guessed an `org_id`/`team_id` could view
   another organization's team name, description, and member roster. Fixed by
   adding the same membership check `list_teams` already has. Regression
   tests: `tests/test_team_view_idor.py`.

7. **`remove_member` had no owner-role protection (`routes/organizations.py`
   + `services/multi_tenancy.py`).** `update_member_role` already blocks a
   non-owner from touching an `owner` role (2026-07-25 fix above), but
   `remove_member` had no equivalent check anywhere in the call chain — gated
   only by `org_admin_required` (owner *or* admin), with the service method
   deactivating any membership with zero role-hierarchy logic. An org `admin`
   could remove the actual `owner`'s membership and seize effective control.
   Fixed by mirroring `update_member_role`'s owner-only check before calling
   `service.remove_member()`. Regression tests added to
   `tests/test_org_role_escalation.py`.

8. **`api/v1/tools.py`'s direct tool-execution endpoint never set cloud user
   context.** `process_message_isolated`/`process_message_streaming` are the
   only two entry points that call `agent._set_cloud_user_context()`
   automatically (see `services/approval_service.py`'s `_execute_tool` fix,
   2026-07-24 entry above, for the same gap in a different direct-invocation
   path). `POST /v1/tools/execute` calls `agent.tools[tool_name](**params)`
   directly, bypassing both — so any write-scope API key calling a cloud tool
   hit `_get_boto_client()`/GCP/Azure equivalents with no per-user credential
   context, either failing closed today (3-sync-worker deployment) or, on a
   different worker model, risking a cross-request context leak. Fixed by
   setting `agent._set_cloud_user_context(g.api_user.id)` before the call and
   clearing it in a `finally`, same pattern as `_execute_tool`. The
   fixture `_FakeAgent` in `tests/test_api_tools_execute.py` needed the two
   new methods stubbed in — a reminder that a test double for `DevOpsAgent`
   has to grow alongside the real class's method surface.

**Also cataloged, not fixed this pass (lower severity / larger diff, left for
a future pass):** `services/infrastructure_sync.py`'s ~15 `sync_aws_*`
functions repeat an identical get-or-create/update/commit pattern verbatim
(~600 lines could collapse into one `_upsert_resource()` helper) and use
`print()` instead of `logger.error` for swallowed exceptions;
`services/model_failover.py`'s `OpenAIProvider`/`GroqProvider`/`KimiProvider`
are near-identical OpenAI-compatible-API adapters that could share a base
class; `app.py`'s `/api/team/users/<id>/role`/`/delete` duplicate
`routes/admin.py`'s user-management logic with a flatter (but not
independently exploitable) authorization check — both require platform
`role='admin'`, which already has full rights, but it's copy-drifted
boilerplate enforcing different rules for the same operation.
`services/multi_tenancy.py`'s `MultiTenancyService.__init__(user_id=None)`
stores `self.user_id` but no getter method reads it — currently dead (every
call site passes no args), but the same false-safety shape the
`ComplianceService` postmortem (CLAUDE.md) warns about: a per-user-looking
service class whose protection depends entirely on the caller remembering an
external check, which failed once already here (finding #6).

Verified: `scripts/check_security_invariants.py` reports zero violations
after all fixes. Full test suite (with a locally-assembled dependency set —
this sandbox has no preinstalled `requirements.txt`) ran 655 passed / 22
failed, all 22 failures traced to `ModuleNotFoundError` for packages unrelated
to any file touched in this pass (`qrcode`, `joserfc`, `python3-saml` wiring
for SAML/SSO/2FA/Teams-bot tests) — confirmed zero regressions by installing
those and re-running: 0 failures.

**Lesson:** the flag-injection guard from 2026-07-27 protected every function
that existed *at the time it was written*, but three of the five gaps here
were in functions that either already existed and were missed, or a class of
bug that recurs every time a new bare-positional-argument git wrapper is
added — same shape as the SSRF/login-timing lesson in the 2026-07-24 entry
above. Consider whether `_reject_flag_like()` coverage itself is worth
enforcing structurally (e.g. an AST check in
`scripts/check_security_invariants.py` for any `repo.git.<x>(*args)` call
where an arg traces to an unguarded function parameter) rather than relying
on each new git tool's author remembering to call it.

---

## Scheduled audit: CloudWatch monitoring bypassed per-user AWS credentials; one unclassified Terraform tool (2026-08-06)

A routine scheduled review (five parallel agents covering the git
flag-injection guard, `safety.py` risk classification, user/org data
isolation, non-`requests` SSRF vectors, and general code smells/duplication)
found the automated `scripts/check_security_invariants.py` check still
clean, the git flag-injection guard (2026-07-27/08-04 entries above) still
fully applied, and no live-exploitable IDOR — but turned up two real gaps,
both fixed:

1. **`services/proactive_monitoring.py`'s `MetricCollector._collect_cloudwatch()`
   never used per-user AWS credentials.** Every AWS tool in this codebase is
   required to route through `_get_boto_client()`/`credential_service.py` so
   each user's chat-driven actions run under their own stored
   access-key/role-ARN credentials (see CLAUDE.md's "User Isolation" and
   "Credential Storage" sections). This collector was the one exception: it
   called a bare `boto3.client("cloudwatch")` with no user context, even
   though `_check_rule(self, user_id, rule)` — its only caller — already had
   `user_id` in scope and simply never passed it down. In practice this meant
   a `source=cloudwatch` monitoring rule never actually queried the owning
   user's own AWS account; it silently ran under whatever default AWS
   identity (if any) the app server process itself has (e.g. an EC2 instance
   role attached for an unrelated purpose like SSM), and depending on that
   identity's permissions either failed closed with no visible error to the
   user, or — the more concerning case — successfully returned CloudWatch
   metrics belonging to the platform's own AWS account into a specific
   customer's alert/DB record for an arbitrary attacker-chosen
   `namespace/metric_name/dimensions` query string, which is exactly the kind
   of "per-user isolation exists for the DB row but not for the credential
   used to populate it" bug shape the `ComplianceService`/`AIInfrastructureService`
   findings above warn about, just on the AWS-credential axis instead of the
   database-row axis. Fixed by threading `user_id` through
   `MetricCollector.collect()` → `_collect_cloudwatch()` and calling
   `services.credential_service.get_user_boto_client(user_id, "cloudwatch")`
   instead of a bare `boto3.client(...)`; a CloudWatch rule now fails closed
   with a clear "AWS credentials not configured" error (same as every other
   per-user AWS tool) if the owning user hasn't connected AWS credentials,
   rather than silently falling back to the server's own ambient identity.
   Prometheus/Datadog collectors were already using operator-configured
   hardcoded hosts (`# ssrf-safe:`-annotated) and needed no change.

2. **`terraform_providers_lock` had no risk classification
   (`src/agent/safety.py`).** It mutates `.terraform.lock.hcl` (the trusted
   provider-checksum lock file) on disk — the same "writes project state to
   disk" shape as its siblings `terraform_state_push`/`terraform_import`/
   `terraform_force_unlock`, all three already medium risk — but its name
   doesn't start with any auto-detect prefix (`terraform_` isn't one), so it
   silently defaulted to low risk with no user confirmation. Fixed by adding
   it to `medium_risk_tools` next to its siblings.

**Also cataloged, not fixed this pass (lower severity, left for a future
pass):** `services/learning_sandbox.py`'s `generate_mock_result()` has no
dedicated mock branch for `ansible_tools.py`, `alerting_tools.py`
(PagerDuty/OpsGenie), `monitoring_tools.py`, or `pentest_tools.py` — sandbox
mode for these falls through to the generic low-fidelity catch-all, despite
CLAUDE.md's Tool Registration Checklist claiming ansible's sandbox mocking
was "completed and verified." `AIInfrastructureService.delete_template()`
(`services/ai_infrastructure.py:599`) calls `get_template()`, a
no-ownership-filter lookup, and applies no ownership check itself before
deleting — same shape as the `ComplianceService`/`view_team` postmortems in
CLAUDE.md, but currently dead code (no route calls it), so not an active
exploit; flagged so the check gets added *before* a delete route is wired up
rather than after. ~24 broad `except Exception: pass` blocks with no logging
exist across `src/tools/`, `services/`, and `routes/` (mostly benign
optional-lookup cleanup, but a handful inside multi-region AWS aggregation
loops in `aws_tools.py` silently drop a whole region's resources from a
listing on any transient error with zero log signal).

Verified: `scripts/check_security_invariants.py` reports zero violations
after the fixes; both edited files parse and import cleanly. Full
`pytest` run wasn't possible in this sandbox (no preinstalled
`requirements.txt`/dependency set and no network-fetched venv within the
scheduled run's time budget) — verification here relied on AST syntax
checks, a clean module import, and manual call-chain tracing instead;
worth a full `pytest -q` pass next time a session has the dependencies
available.

## Scheduled audit: GCP tools broadly bypassed per-user credentials; `register_targets` unclassified (2026-08-08, PR #121)

A routine scheduled review (five parallel agents covering the git
flag-injection guard, `safety.py` risk classification, user/org data
isolation, non-`requests` SSRF vectors + cloud credential isolation, and
general code smells/duplication) found the git flag-injection guard and IDOR
shape both still clean, `scripts/check_security_invariants.py` still
reporting zero violations — but turned up one real, wide-reaching gap plus
a smaller one, both fixed:

1. **`src/tools/gcp_tools.py` — most GCP tools silently fell back to
   Application Default Credentials (the app server's own ambient GCP
   identity) instead of the requesting user's linked GCP credentials.** This
   is the exact bug class already found and fixed once for GCP Secret
   Manager (`_get_secretmanager_client`, prior audit) and for AWS CloudWatch
   (`services/proactive_monitoring.py`, 2026-08-06 entry above) — but it
   turned out to be far more widespread on the GCP side than either of those
   fixes covered. **~25 functions constructed a GCP SDK client directly with
   no `credentials=` argument at all**: `list_compute_instances`' all-zones
   path (`compute_v1.ZonesClient()`), `create_compute_instance`/
   `delete_compute_instance` (`InstancesClient()`/`ImagesClient()`),
   `list_cloud_functions` (`CloudFunctionsServiceClient()`), Cloud Run list/
   deploy/delete (`run_v2.ServicesClient()`), Pub/Sub publish/subscribe
   (`PublisherClient()`/`SubscriberClient()`), BigQuery dataset list/create/
   delete (`bigquery.Client()`), Cloud Logging (`logging.Client()`), Cloud
   SQL restart/delete (`SqlInstancesServiceClient()`), GKE resize/delete
   (`container_v1.ClusterManagerClient()`), firewall list/create/delete
   (`compute_v1.FirewallsClient()`), Cloud Functions v2 delete
   (`FunctionServiceClient()`), and disk/snapshot list/create/delete
   (`SnapshotsClient()`/`DisksClient()`). `create_cloud_sql_instance` had an
   even more explicit version of the same bug written directly into the
   code: `credentials = user_creds if user_creds else google.auth.default()[0]`.
   Fixed by adding a single shared `_get_gcp_credentials_kwargs()` helper and
   routing every one of the ~25 bare client constructions through it, plus
   rewriting `create_cloud_sql_instance` to raise the same "GCP credentials
   not configured" error every other GCP tool raises instead of falling back
   to `google.auth.default()`.

   **PR review caught that the first version of this fix didn't actually
   close the gap it documented.** The initial `_get_gcp_credentials_kwargs()`
   returned `{}` when the user had no linked credentials, so every one of
   those ~25 client constructions still ran with no `credentials=` argument
   at all in that case — i.e. still fell back to ADC, for any authenticated
   user with no GCP creds configured (or, since `_get_user_gcp_credentials()`
   ends in a bare `except Exception: return None, None`, any user hitting a
   *transient* DB/key-decode error too), regardless of the shared helper's
   own docstring naming that exact behavior as the bug being fixed. The
   commit's PR description had correctly caveated this as a known residual
   gap rather than claiming full closure, but the reviewer's fix was the
   right call over documenting a known hole: **`_get_gcp_credentials_kwargs()`
   now raises "GCP credentials not configured" when the user has none linked,
   the same fail-closed contract `_get_boto_client` (AWS) and
   `_get_azure_client` (Azure) already enforce**, rather than degrading to
   ADC — closing the gap even for a caller-supplied explicit `project_id`,
   which previously bypassed `_resolve_project_id`'s only failure path. The
   `GCP_PROJECT_ID` env var / `GOOGLE_APPLICATION_CREDENTIALS` self-hosting
   path referenced in `app.py`'s `save_gcp_credentials`/`get_gcp_config_status`
   was checked and confirmed dead — zero callers anywhere in the repo — so
   there was no live self-hosted use case this fail-closed change could break.

   The same review also flagged that credential resolution ran twice per
   client construction in `_get_gcp_client()` (once for the project-ID
   fallback, once inside the credentials helper) and in `create_compute_instance`/
   `create_disk_snapshot` (once per client, two clients each) — each
   resolution round-trips the DB and writes a plaintext service-account
   private key to a temp file before deleting it, so doing it twice doubles
   both the DB load and the window the plaintext key sits on disk. Fixed by
   resolving credentials exactly once per function and reusing the result
   for every client construction in that function; verified via a mocked
   call-count assertion (`_get_user_gcp_credentials` called exactly once per
   `_get_gcp_client`/`create_compute_instance` invocation) rather than just
   reading the diff.

2. **`register_targets` (AWS ELB target-group tool, `src/tools/aws_tools.py`)
   had no risk classification.** It registers arbitrary instances/IPs with a
   load-balancer target group — i.e. it can redirect live production traffic
   to an attacker- or agent-chosen target — but its sibling
   `deregister_targets` is explicitly medium-risk while `register_targets`
   itself was absent from both `high_risk_tools`/`medium_risk_tools` and
   doesn't match any auto-detect prefix, so it silently defaulted to low risk
   with no confirmation prompt. Fixed by adding it to `medium_risk_tools`
   next to `deregister_targets`.

**`services/ai_infrastructure.py`'s `delete_template()` IDOR was deliberately
NOT touched by this PR** despite being caught by the same audit sweep — PR
#120 (open concurrently, same base commit) already fixes the identical gap
independently. Landing both would conflict on the same hunk; this PR's
copy was reverted before merge so #120 owns that fix. See #120 (or the entry
directly below once merged) for the writeup.

**Lower-severity items also cataloged this pass, not fixed:** `app.py`'s
`api_chat` and `api_chat_stream` duplicate a ~60-line context-building block
(memory/credential-status/trial context) almost verbatim, and the streaming
path additionally calls `get_active_skills_context()` and handles
`page_context`/`resource_context` that the non-streaming path never gets —
a real feature gap (skills-engine injection and page/resource awareness
silently don't apply to non-streaming `/api/chat`), not just duplication,
but a large enough refactor to warrant its own pass rather than folding into
a security-audit commit. `get_compliance_service()`/`get_ai_infrastructure_service()`/
`get_analytics_service()`/`get_multi_tenancy_service()` singleton-getter
functions are defined with zero callers (every route instantiates the
service class directly instead). `services/infrastructure_sync.py`'s
`check_rightsizing_opportunity()` swallowed CloudWatch errors with a bare
`except Exception: pass` inside a per-resource cost-recommendation loop —
fixed with a one-line `logger.warning()` (the module had no logger at all;
added a standard `logging.getLogger(__name__)`). `get_commit_history()`
(`src/tools/git_tools.py`) was the one function whose caller-supplied
`branch` reached `repo.iter_commits()` without a `_reject_flag_like()` call;
confirmed non-exploitable today only because GitPython 3.1.58 itself blocks
the one file-write-capable `rev-list` flag internally (an implicit
library-level protection, not this app's own guard) — added the guard call
anyway for defense-in-depth/consistency rather than relying on a pinned
dependency's internal blocklist staying exactly as-is. `app.py:_validate_webhook_url`
reimplements a weaker single-IP DNS check instead of calling
`assert_safe_external_webhook_url` — low severity since it's create-time
validation only and the actual send path already uses the shared stricter
helper; left for a future pass.

**Verification:** `scripts/check_security_invariants.py` reports zero
violations after the fixes. All edited files
(`src/tools/gcp_tools.py`, `src/agent/safety.py`,
`services/infrastructure_sync.py`, `src/tools/git_tools.py`) compile
cleanly. Full `pip install -r requirements.txt` failed on an unrelated
pre-existing package (`multi-key-dict` wheel build failure under modern
setuptools) and the sandbox's system `cryptography` package conflicts with a
pip-installed build (`pyo3_runtime.PanicException: Python API call failed`),
so a full `pytest -q` run wasn't possible here either — same constraint as
the 2026-08-06 audit. Verification instead used targeted `pip install` of
the specific packages needed (`google-cloud-compute`, `google-cloud-storage`,
`google-cloud-container`, `google-auth`, `boto3`), then, after stubbing the
two GCP submodules not available on PyPI/in this sandbox
(`google.cloud.sql_v1`, `google.cloud.monitoring_v3`): a real isolated
import of `gcp_tools.py` confirming `get_tools()` still returns 42 tools;
mocked calls confirming `_get_gcp_credentials_kwargs()` and `_get_gcp_client()`
both raise when the user has no linked credentials — including with an
explicit `project_id`, closing the exact bypass the reviewer flagged — and
that a real client construction (`InstancesClient`) receives the correct
`credentials=` kwarg when creds are present; call-count assertions
confirming `_get_user_gcp_credentials()` is invoked exactly once per
`_get_gcp_client()`/`create_compute_instance()` call; and direct
`SafetyValidator.validate_tool_call()` calls confirming `register_targets`
now matches `deregister_targets`'s medium-risk classification. Worth a full
`pytest -q` pass next time a session has the dependency set available.
**Follow-up (same day):** that verification was real but lived only in the
commit message — no test file was committed, so nothing guarded the contract
against regression. Added `tests/test_gcp_credential_fail_closed.py` (4 tests):
three pin the fail-closed contract on `_get_gcp_credentials_kwargs()` itself
(raises when the user has none linked, **never returns `{}`** — the empty dict
is the specific regression, since `SomeClient(**{})` builds a credential-less
client that resolves to ADC — and threads real credentials through when
present), plus one AST-based structural test asserting **every** GCP client
construction in `gcp_tools.py` passes credentials. The structural one is the
important half: the original bug wasn't a wrong helper, it was ~25 call sites
written without any `credentials=` argument, so a newly-added tool would
reopen the fallback for itself alone with nothing to catch it. It carries a
`len(examined) >= 20` guard so it can't silently go vacuous if the detection
heuristic drifts, and was negative-tested (reverting one `FirewallsClient` to
a bare constructor makes it fail with the exact line number). Full suite on
this branch: **684 passed**; the 7 failures seen locally are all one
Windows-only `UnicodeDecodeError` from `pathlib.read_text()` defaulting to
cp1252 (`scripts/check_security_invariants.py:179` and `test_tool_counts.py`
read UTF-8 source files without an explicit `encoding=`) — they pass on
Linux CI. **Fixed immediately after (same session):** all 16 bare
`Path.read_text()` calls across `scripts/check_security_invariants.py`,
`scripts/build_cf_template.py`, `tests/test_iam_policies.py`, and
`tests/test_tool_counts.py` now pass `encoding='utf-8'`. Fixing the encoding
then exposed a **second, more consequential Windows bug hiding behind it**:
`check_security_invariants.py` built its relative path with
`str(path.relative_to(REPO_ROOT))`, which yields `routes\auth.py` on Windows
while both exemption sets hold forward-slash paths like `routes/auth.py` — so
**every exemption silently failed to match on Windows**, and the scanner
reported `routes/auth.py`'s own `check_password()` calls as violations of the
rule that explicitly exempts that file. Switched both call sites to
`.relative_to(REPO_ROOT).as_posix()`. Note the failure mode: the encoding
crash was *masking* a correctness bug in the security scanner, so "it only
fails on Windows" was not the same as "it doesn't matter" — the scanner was
wrong on that platform, not merely unrunnable. Both fixes negative-tested
(injecting a raw `requests.get()` into a scanned non-exempt file still fails
the test; reverting it passes), confirming the exemption fix didn't over-broaden
into suppressing real detections. Full suite on Windows after the fix:
**691 passed, 1 skipped, 0 failed** (was 684 passed / 7 failed). **Also found while testing:** `_get_gcp_client()`
is currently unreachable in *every* environment including production — its
first statement imports `sql_v1`, and `google-cloud-sql` is commented out of
`requirements.txt` as "Package doesn't exist on PyPI", so the function raises
`ImportError` before any credential logic runs. The ~25 direct client
constructions elsewhere in the module are the paths that actually execute.
Not fixed here (pre-existing, and GCP has zero live users — see below), but
it means the `_get_gcp_client` half of this fix is currently theoretical.
**Live blast radius at time of fix (queried against production):** 8 users
total, 1 cloud credential row in the entire `user_cloud_credentials` table
(a single AWS credential), **zero GCP and zero Azure credentials**; and the
EC2 host has no ambient GCP identity to escalate to either — no
`GOOGLE_APPLICATION_CREDENTIALS`, no gcloud ADC file under `ubuntu` or
`root`, no `GCP_PROJECT_ID`, and `169.254.169.254` is AWS IMDS which 404s
Google's metadata paths. So the ADC fallback had nothing to fall back to and
was not exploitable in production; this was fixed on the correct-by-
construction argument, not an active incident, and the fail-closed switch was
deliberately made while the blast radius is zero rather than after the first
GCP user exists.

## Scheduled audit: `devops_operations_tools` thread-local context never cleared (2026-08-11)

A routine scheduled review (four parallel agents covering tool risk
classification, IDOR/user-isolation, git flag-injection + guardrail-gated
entry points, and general code smells/duplication) found the first three
areas clean — `scripts/check_security_invariants.py` still zero violations,
every destructive/mutating tool correctly classified, no new IDOR shape, all
18 git tools with a caller-supplied positional still guarded by
`_reject_flag_like()`, no new chat-to-agent entry point bypassing
`sanitize_input`/`validate_message`/`screen_message`. The smells pass found
one real gap in the same per-request context-isolation pattern documented
above under "Concurrency Model: the shared `agent` singleton", plus a few
small cleanups:

1. **`src/tools/devops_operations_tools.py` (cost analysis, change
   governance, compliance tools) had no `clear_user_context()`, unlike its
   `aws_tools`/`azure_tools`/`gcp_tools` siblings, and `core.py`'s
   `_clear_cloud_user_context()` had no call for it at all.** The set side
   (`_set_cloud_user_context`) *did* set it, via
   `set_devops_context(user_id)`, but the clear side never reset it back to
   `None`. Worse, the set call was wrapped in a bare
   `except (ImportError, Exception): pass` — the only one of the four
   provider blocks in that function with no logging on failure, unlike its
   AWS/Azure/GCP siblings which each `logger.warning()` on both `ImportError`
   and generic exceptions. Net effect: after a request finished, the
   thread-local devops-operations user_id stayed set to that request's user
   indefinitely on that OS thread, until the next explicit `set_user_context`
   call overwrote it. `process_message_isolated`/`process_message_streaming`
   both call `_set_cloud_user_context` at the very start of every real
   request, so the normal request path was self-healing — but
   `services/approval_service.py`'s `_execute_tool()` (the approve-and-run
   path for a deferred high-risk tool call) sets the requester's context,
   runs the tool, then calls `agent._clear_cloud_user_context()` in a
   `finally` block specifically to leave a clean slate — and that clear
   never actually touched the devops context, leaving the approver-run
   request's user_id sitting on the thread for cost/compliance/
   change-governance tools to potentially read on some later call that
   doesn't set its own context first. Fixed by adding
   `clear_user_context()` to `devops_operations_tools.py` (identical shape
   to `aws_tools.clear_user_context()`), wiring it into
   `_clear_cloud_user_context()`, and switching the set-side's silent
   `pass` to the same logged `except ImportError` / `except Exception`
   pattern its siblings use. Regression test:
   `tests/test_devops_context_clear.py`.

2. Two defense-in-depth/consistency cleanups, neither an active
   vulnerability: `src/agent/safety.py` listed `delete_pod`/
   `delete_configmap`/`delete_k8s_secret` in **both** `high_risk_tools` and
   `medium_risk_tools` — harmless today since `high_risk_tools` is checked
   first, but a latent trap if someone later removes just the high-risk
   copy assuming the medium one still covers it; removed the redundant
   medium-risk copies. `src/tools/git_tools.py`'s `git_fetch` was the one
   function taking a caller-supplied `remote` param that skipped
   `_reject_flag_like()` (its siblings `git_pull`/`git_push`/
   `git_force_push_branch` all guard the same parameter) — not currently
   exploitable since `repo.remote(name)` is a pure-Python dict lookup that
   raises `ValueError` on an unknown name rather than shelling out, but
   added the guard for parity in case this ever changes.

3. `routes/api_gateway.py`'s `/v1/agent` handler had a redundant bare
   `if len(message) > 10000` check that duplicated
   `services/input_sanitizer.py`'s `MAX_MESSAGE_LENGTH` (also 10000),
   running with its own hardcoded literal a few lines before
   `validate_message()` enforces the identical limit anyway — removed the
   duplicate so the limit can't drift out of sync between the two checks in
   this one entry point (the other three guardrail-gated entry points don't
   have this duplicate).

Two findings intentionally **not** changed, flagged for a human decision
instead: `services/model_router.py`'s `DEFAULT_TIER_MODELS['business']` is
configured identically to `professional` (`claude-sonnet-4-6`, including a
matching `display_name`), while CLAUDE.md's tier table documents `business`
($299/mo) as `claude-opus-4-6` — this reads as either a deliberate
cost-driven decision that never made it back into the docs, or an unshipped
regression, and changing which model $299/mo subscribers get isn't something
a scheduled code-review pass should decide unilaterally. `services/sandbox.py`'s
`run_sandboxed()`/`run_script_sandboxed()` duplicate ~40 lines of Docker
subprocess/timeout/cleanup control flow and `app.py` has 8 inline
`current_user.role != 'admin'` checks that could use the existing
`admin_required` decorator instead (which also logs denied attempts) — both
real but larger refactors than this pass's scope, left for a dedicated
follow-up.

## Scheduled audit: two more `git_tools.py` functions missing the flag-injection guard (2026-08-12)

A routine scheduled review (four parallel agents covering per-user service
IDOR, tool risk classification, SSRF/git-flag-injection guard coverage, and
thread-local context leaks + code duplication) found three of the four areas
clean: no exploitable IDOR in any `services/*.py` class or `routes/*.py`
handler (two latent-but-not-currently-reachable footguns noted below), no
tool-safety classification gaps in the `<provider>_<verb>_<noun>` shape (the
class that produced `git_delete_branch`/`register_targets` previously), no
SSRF gap in any non-`requests` network call, and no thread-local context
leak or exploitable code duplication (`aws_tools.set_user_context()` being
called directly from `pentest_tools.py` without a matching clear was noted
as a minor pattern smell, not a live leak — the request's own
`_clear_cloud_user_context()` still runs in every current call path).

The git-flag-injection sweep found the real issue: `_reject_flag_like()`
(the guard added 2026-08-01 and extended 2026-08-04 after a live-verified
RCE) is opt-in per function, and two functions that predate both of those
fixes had never been swept into it:

1. **`git_add_remote(repo_path, name, url)`** — `name` reached
   `repo.create_remote(name, url)` (→ `git remote add <name> <url>`) as a
   bare positional with zero validation, unlike every other
   branch/remote/tag-naming function in the file. `name="-f"` is parsed by
   `git remote add` as the `-f` (fetch) flag instead of a literal remote
   name, triggering an implicit fetch from the caller-supplied (and
   SSRF-validated only for reachability, not trust) URL immediately on add —
   before any confirmation step, which shows "add remote X" and has no way
   to know X is a flag.
2. **`git_show_commit(repo_path, commit_sha)`** — `commit_sha` reached
   `repo.commit(commit_sha)` unguarded, even though its sibling
   `git_show_file_at_commit` already guards the identical parameter name
   before an equivalent `repo.git.show(...)` call. `repo.commit()` resolves
   through GitPython's rev-parse machinery, which can fall through to the
   `git` binary for revision specs it can't parse locally — the same
   dash-prefixed-positional ambiguity the guard's own docstring warns about.

**Fix:** both now call `_reject_flag_like()` before the git call (identical
pattern to every other guarded function), and both are now classified
medium-risk in `safety.py` (`git_add_remote` alongside `git_clone_repository`
as a "fetches from a caller-supplied remote" tool; `git_show_commit`
alongside `git_show_file_at_commit`/`git_blame_file` as a flag-guarded read
tool). No test suite could be run in this environment (`pytest` not
installed, no venv present) — verified only via `ast.parse()` syntax check
on both edited files; a fresh session with a working test environment should
run `tests/test_new_tools.py`/`tests/test_security_invariants.py` to confirm
no regression.

**Not changed, flagged for awareness only (not currently exploitable):**
`services/multi_tenancy.py`'s `MultiTenancyService.__init__` stores
`self.user_id` but no method ever reads it — every getter is a bare
`Model.query.get(id)` with the entire ownership-check burden left to the
caller (`routes/organizations.py` currently does this correctly everywhere).
`services/api_gateway.py`'s `APIGatewayService` has the same shape, and
several of its methods take an *optional* `user_id` param that **defaults to
`None`, which skips the ownership check entirely** — every current call site
passes `current_user.id`, so nothing is live-exploitable today, but a future
call site that omits the parameter would silently grant cross-user access.
Both are the same structural class as the `ComplianceService`/`view_team`
bugs fixed earlier (`self.user_id` stored but not enforced) — worth a
dedicated hardening pass (make `user_id` required, not optional, and have
the service enforce it internally rather than trusting every caller) rather
than a scheduled-audit-scope fix.

**Lesson, same as the 2026-08-04 entry:** this guard is opt-in per function
and still not enforced by an automated check — a security audit has to walk
every bare-positional `repo.git.*`/`repo.<method>(...)` call site in this
file by hand each time, not just spot-check the ones already known to be
guarded.

## Drift detection stored everything in per-process memory (FIXED 2026-08-12)

User-reported: "drift detection does not generate a report or findings if
there is a drift or not." `services/drift_detection.py`'s
`DriftDetectionService` kept baselines and reports in plain Python dicts on
a module-level singleton (`get_drift_service()`). Production runs 3
gunicorn workers, each its own process: a baseline added on the worker that
served that request was invisible to a scan landing on a different worker
(`get_baseline_count()` returns 0 -> "No baselines configured"), and any
report that *did* get generated only existed in that one worker's memory --
gone on the next request to a different worker, and wiped entirely on every
deploy. Same class of bug as the MCP OAuth connector fix above, in a
different feature. Fixed by adding `DriftBaselineModel` / `DriftReportModel`
(models.py) and rewriting the service's persistence methods to read/write
the DB instead of dicts, keeping the public API (dataclasses, method
signatures) unchanged so `routes/drift.py` and the templates needed no
changes. Regression tests in `tests/test_drift_detection.py` build a *new*
`DriftDetectionService()` instance per check (standing in for "a different
worker") -- 3 of 4 fail against the old in-memory code, confirming they
catch the real bug.

**Not fixed in this pass, flagged for a follow-up:** `_get_actual_state()`
never calls AWS -- it returns hardcoded simulated data for 3 resource types
(EC2 instance, security group, S3 bucket) and an empty dict for the other 8
baselineable types (which would flag every property as "removed" drift
regardless of real state). Persistence is now correct, but the comparison
data itself is still a prototype/demo, not real infrastructure state.

## Schema migration only ran under `python app.py`, never under gunicorn (FIXED 2026-08-12)

Root cause behind the drift-detection fix above, and two earlier incidents
(`mcp_oauth_clients` table missing, `infrastructure_changes.organization_id`
column missing): `db.create_all()` and the auto-migration `ALTER TABLE`
column loop lived only inside `if __name__ == '__main__':`, which never
executes when gunicorn imports the module as `app:app`. `SubscriptionTier`
rows only existed in prod because `scripts/deploy_ec2.sh` ran
`db.create_all()` once, manually, during initial EC2 provisioning — every
table added to `models.py` since then silently never got created
automatically. This exact gunicorn-vs-`__main__` gap had already been found
and fixed independently four times in this file, for four *other* startup
steps (eager agent init, public template seeding, workflow template seeding,
background scheduler) — each fix left a comment explaining the gap, but none
of them touched the migration logic itself, which is the one that actually
matters most. Fixed by extracting the table-creation + column-migration
logic into `_run_schema_migration()` and calling it from both the
gunicorn-import block and the `__main__` block. Regression test
(`tests/test_schema_migration_gunicorn.py`) statically asserts the call site
is reachable from the gunicorn-import guard — a dynamic test can't exercise
that branch directly since it's deliberately gated off under pytest, same
as the other four startup steps next to it. Verified the test fails against
the pre-fix source.

**Immediate unblock (same day):** manually ran `db.create_all()` on the EC2
instance via SSM to create the two missing `drift_baselines`/`drift_reports`
tables so drift detection worked without waiting for a deploy.
