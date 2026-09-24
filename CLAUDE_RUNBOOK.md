# DevOps Agent - Runbook & Historical Fixes

> Historical bug fixes, resolved issues, and gotchas.\n> See CLAUDE.md for active development guidance.

This document archives fixed issues and their solutions for reference. Most issues here are already resolved in the codebase and documented in git history.

## Resolved Issues / Gotchas

| Issue | Solution |
|-------|----------|
| **Scheduled MCP OAuth audit found a DCR client with empty `redirect_uris` bypassed the redirect allowlist entirely, plus `/mcp/oauth/authorize` had no account lockout on password guessing (FOUND & FIXED 2026-09-18)** | Routine rotating security audit (day-of-month mod 6 landed on `routes/mcp.py` OAuth flows). **Bug 1 — redirect_uri allowlist bypass, critical.** `oauth_authorize()` computed `allowed_redirect_uris = client_record.get('redirect_uris') or None`, then only enforced membership with `if allowed_redirect_uris and redirect_uri not in allowed_redirect_uris`. A DCR client registered via the fully open, unauthenticated `POST /mcp/oauth/register` with `redirect_uris: []` (or the key omitted, or `null`) collapsed to `None`, which made the whole check a no-op — that client could then send an authorization code to *any* `redirect_uri`, https-scheme only. This is the exact same bug class the 2026-08-30 fix closed for the *built-in* `claude-connector` client (see that entry below); the DCR path had an independent copy of it. Exploit: register a client with an empty array, get a `client_id` with zero restrictions, then phish a victim with a link on the real `devopsagent.io` domain (`/mcp/oauth/authorize?client_id=<id>&redirect_uri=https://attacker.tld/cb&...`) — the victim sees a legitimate host and a plausible `client_name` (also attacker-supplied), logs in, clicks Authorize, and their auth code — redeemable for a full-scope MCP access token covering all 746 cloud/infra tools — is sent straight to the attacker. **Fixed at both ends:** `oauth_register()` now rejects registration outright (`400 invalid_client_metadata`) unless `redirect_uris` contains at least one non-empty string (RFC 7591 §2 requires it for the `authorization_code` grant anyway); and `oauth_authorize()` now always keeps `allowed_redirect_uris` as a real (possibly empty) set and always enforces membership — an empty allowlist now means "reject every redirect_uri", never "skip the check" — so even a pre-existing DB row with an empty list (from before this fix, or written directly rather than through the now-validating registration endpoint) fails closed. `redirect_uri` was also made mandatory (previously validated only `if redirect_uri:`, so omitting it entirely skipped both the https check and the allowlist check). **Bug 2 — no account lockout, high.** The same POST handler correctly used `_run_timing_safe_password_check()` (no timing side-channel — see the entry above) but never called `User.is_locked()`/`record_failed_login()`, and carried no `@limiter.limit` of its own (falling back to the blueprint-wide default: 500/day, 100/hour per IP — no per-account limit at all, and ~10x weaker than `/login`'s explicit `10 per minute`). A known email could be brute-forced through this endpoint indefinitely, regardless of how many attempts `/login` itself would already have locked out. Fixed by wiring in the same `is_locked()` (checked before the password comparison)/`record_failed_login()` (on failure)/`update_last_login()` (on success, resetting the counter) calls `/login` uses, plus a matching `@limiter.limit("10 per minute")` on both `/mcp/oauth/authorize` and its `/authorize` alias. Regression tests added to `tests/test_mcp_oauth.py` (`TestEmptyRedirectUrisBypass`, `TestOAuthAuthorizeAccountLockout` — 7 new tests); full suite re-run clean (999/1000 passing, the one failure being a pre-existing environment-only test unrelated to this file that needs a real `ANTHROPIC_API_KEY` exported). **Lesson:** a secondary authentication entry point that reimplements a primary route's password check has to reimplement *every* security invariant that check enforces, not just the ones that already have a name and a prior incident attached — this is the second time `oauth_authorize()` specifically has been the copy that only got half the fix (see the 2026-08-30 and login-timing entries), and the general pattern (a fix applied to one call site not reaching a duplicate in a sibling file) is the same one CLAUDE.md's guardrails-pipeline and SSRF-guard sections already call out. |
| **`list_storage_account_keys` had no risk classification at all — any user could disclose a live Azure storage account key with zero confirmation prompt (FOUND & FIXED 2026-09-16 scheduled audit)** | Routine code-vulnerability/smell/duplicate scan. Cross-referenced every one of the 744 registered tool names against `src/agent/safety.py`'s `high_risk_tools`/`medium_risk_tools` sets and its auto-detection prefixes, looking for the same disclosure-class gap already fixed three times before (`get_secret_value`, `create_ec2_keypair`, `generate_s3_presigned_url` — see the 2026-08-23 entry). Found it a fourth time: `azure_tools.list_storage_account_keys()` returns `k.value` — the raw plaintext storage account access key, a live bearer credential granting full read/write/delete over every blob/queue/table/file in the account until manually regenerated — directly in the tool result. `list_` isn't a monitored prefix in either direction, and the tool wasn't in either explicit set, so it defaulted to low risk: no confirmation, straight into the chat/tool-trace/LLM-provider path, same exposure class as the three prior fixes. Its sibling `regenerate_storage_key` has the identical disclosure shape (returns the newly-generated key's `value`) but was only medium-risk, presumably classified for the *mutation* (rotating a key breaks anything still using the old one) without anyone separately reasoning about the *disclosure*. **Fixed by adding `list_storage_account_keys` to `high_risk_tools` and moving `regenerate_storage_key` there from `medium_risk_tools`**, both with an inline comment naming the precedent. No sandbox mock or test referenced either tool name, so nothing else needed updating. **Verified:** `scripts/check_security_invariants.py`'s two AST checks still pass; `py_compile`/AST-parse on the edited file; confirmed by source read that `list_secrets_manager_secrets` (AWS), `list_secrets` (GCP), `list_k8s_secrets`, and `list_iam_access_keys` are all metadata-only (names/ARNs/dates, never values) so none of them have the same gap. Full `pytest` wasn't possible in this sandbox (`pip install -r requirements.txt` fails on the same pre-existing `multi-key-dict` wheel-build error noted in earlier scheduled-audit entries). **Lesson:** the "does this tool return decrypted/raw credential material" question has to be asked per-tool, not inferred from the verb — `list_`/`get_`/`regenerate_` all read as ordinary read/update operations, and three of the four tools now carrying this exact justification comment have names that don't contain the word "secret" at all. |
| **Every form endpoint except four in `routes/auth.py` accepted a cross-origin POST (FOUND & FIXED 2026-09-19)** | `app.py` set `WTF_CSRF_CHECK_DEFAULT = False` to exempt the JSON API surfaces, with the comment "CSRF enforced on form endpoints via `@csrf.protect`" — but **no `@csrf.protect` decorator was ever added to any route**. Only four auth routes (`/login`, `/signup`, `/forgot-password`, `/reset-password`) validated by hand, through `routes/auth.py`'s `_check_csrf()`. The result was a codebase that *looked* CSRF-protected from three directions at once (an initialized `CSRFProtect(app)`, a helper function, and templates emitting `csrf_token` inputs) while every cookie-authenticated form POST outside those four — `/profile`, organization invites and settings, compliance policy forms, API-key creation — accepted a cross-origin submission. The tell was that the config comment described a mechanism that did not exist; nothing fails when the second half of a two-part design is never written. Fixed with a single `@app.before_request` hook, `_enforce_csrf_on_form_submissions()`, that gates on **MIME type rather than route**: only `application/x-www-form-urlencoded` and `multipart/form-data` are checked, because those two are CORS "simple requests" a cross-origin page can send with the victim's cookies, while `application/json` requires a preflight an attacker cannot satisfy. That inversion is what makes it safe by default — a new JSON endpoint needs no exemption and a new form endpoint is covered automatically, so this cannot rot the way a per-route decorator list does. The hook mirrors Flask-WTF's own `csrf_protect` and reads its private `_exempt_blueprints`/`_exempt_views` sets so `csrf.exempt(...)` still works, **which makes the exact `flask-wtf` pin load-bearing** — re-verify against `flask_wtf/csrf.py` if it moves. Rejections return a **303 redirect with a flash**, not a bare 400, since a failure here is far more often a stale session than a forgery; the referrer is passed through `_is_safe_redirect()` first, because on a genuinely forged request it points at the attacker's page and bouncing the victim back to it would turn the error handler into an open redirect. 8 tests in `tests/test_csrf_enforcement.py` assert **both** halves (form-without-token rejected, JSON-without-token still allowed) — a regression here is silent, as the forms keep working and merely stop being checked. |
| **`services/cache_service.py`: a delete could outlive itself in the memory fallback (2026-09-19)** | Mostly cleanup, but with one real fix buried in it — worth separating, because the rest of the diff genuinely is cosmetic. `set`/`delete`/`clear` returned an unconditional `True` that no caller or test ever read — now `None` (`python:S3516`, 3 BLOCKERs). `set`'s Redis-failure branch and its no-Redis branch were byte-identical copies of the same memory-cache write; collapsed into one fall-through. `clear()`'s `try/except redis.RedisError` was dead: it wraps only `delete_pattern("*")`, which catches `RedisError` itself and never propagates. Its early `return True` did make the following `self.memory_cache.clear()` unreachable whenever Redis was configured, **but that was harmless, not a leak** — `delete_pattern` strips the `*` to the bare key prefix and removes every matching in-memory key, and all memory keys come from `_make_key()` so all carry that prefix. The trailing `memory_cache.clear()` was always redundant, never a missed cleanup. **`delete()` was the opposite case and is a real fix:** it also returned early on Redis success, but nothing else removed the in-memory copy, so a value written to `memory_cache` by `set()`'s fallback during a Redis outage survived its own `delete()` and could later be served by `get()`'s fallback as a live value. It now always `pop`s the local copy. Narrow — it needs a Redis outage during `set` and a recovery before `delete` — but it is a behaviour change, not a readability one. Verified by `tests/test_tool_cache.py` + `tests/test_services.py` + `tests/test_csrf_enforcement.py` (51 passed), and the full suite at 1003 passed / 1 skipped. |
| **SonarQube's first run found the entire ChatOps command surface was dead code that would raise on every invocation (FOUND & FIXED 2026-09-12)** | Stood up a local SonarQube (`docker-compose.sonar.yml`) and scanned the repo for the first time: 2203 issues, of which **20 BLOCKER**. Eleven of those were `python:S930` ("Add 1 missing arguments") clustered in `services/chatops_service.py`, and they turned out to be one bug with one cause. The incident engine and monitoring service had been refactored to be per-user — `get_stats(user_id)`, `get_status(user_id)`, `list_incidents(user_id, ...)`, `get_incident(user_id, incident_id)`, `acknowledge_incident(user_id, incident_id, user)`, `list_playbooks(user_id)`, `execute_playbook(user_id, incident, ...)`, `analyze_incident(user_id, incident_data)`, `process_alert(user_id, alert_data)` — but **`chatops_service.py` was never updated**, so every one of `/status`, `/incidents`, `/incident`, `/ack`, `/playbooks`, `/execute`, `/analyze` raised `TypeError` the moment it ran. `process_message` catches bare `Exception` and returns `f"Error executing command: {e}"`, so the feature failed as a cryptic chat reply rather than a log-visible crash, which is why it survived. **Two worse defects sat in the same file that Sonar did *not* flag,** found by reading the signatures while fixing the ones it did: `_cmd_resolve` called `engine.resolve_incident(incident_id, resolution)` against `resolve_incident(self, user_id, incident_id, resolution=None)` — the **arity matches**, so it silently passed an incident id as a `user_id` and a resolution note as an incident id; and `_cmd_alerts` called `service.get_alerts(status='firing')`, a method that **does not exist** (the real API is `get_active_alerts(user_id)`, which also returns dicts where the handler did attribute access). **The fix is not simply to pass the id through.** ChatOps `user_id` is a *chat platform* identity (Slack `U01ABC123`), the engine keys on `User.id`, and no mapping between them exists anywhere in the codebase — forwarding it would have read an empty namespace or another user's. So `process_message` gained an explicit `app_user_id: int` parameter distinct from the platform `user_id`; per-user handlers resolve it through `_require_app_user()`, which raises `_UnresolvedAppUser` and is rendered as a plain "this chat identity is not linked to an account" reply. `routes/chatops.py`'s `@login_required` test endpoint passes `current_user.id`; the Slack and Teams webhooks pass nothing and get the honest refusal. `services/webhook_integrations.py` had the identical shape (`process_alert` with no user) and got the same treatment: `process_webhook` takes an optional `app_user_id`, and `_handle_failure_event` logs and returns instead of creating an incident in a namespace it cannot determine. **Still open (design decision, not a bug):** there is no Slack/Teams→`User` account-linking model, so ChatOps remains non-functional from chat itself — it now says so instead of erroring. Building that mapping is the follow-up. **Lesson:** a `try/except Exception` around a command dispatcher converts "this entire feature is broken" into "this command returned a confusing message", and nothing else in the system distinguishes those. Static analysis caught the arity mismatches; only reading the callee signatures caught the same-arity wrong-order call and the nonexistent method, which is the reminder that S930's absence is not evidence a call is correct. |

| **Fabricated instance id laundered into conversation history; negated-denial false positive in the new guard (2026-09-05)** | Follow-up turn to the 2026-09-04 incident. Asked "create an ec2b instance using ubuntu on t3.micro", the agent declined and reported "Your earlier Ubuntu t2.micro (i-05869a36c04f538cb) is still running fine" — **re-asserting the previous turn's fabricated instance as verified fact**, along with the fabricated AMI id `ami-0d7f022123f8ff19d`. It also explained that "instance launch requests keep getting routed to the wrong tool"; production `agent.log` for 2026-09-05 shows **one turn, zero tool calls**, one `Progressive tool loading: 52/697` line and no not-offered/unknown-tool errors — so nothing was routed anywhere and the diagnosis was itself confabulated. The `ec2b` typo was ruled out: replaying that message through `select_tool_definitions` gives the same 39 tools with `create_ec2_instance` and `find_ami` both offered. Production HEAD was `a403e4b` (#171) — the `_fabricated_action_claim` guard was still an open PR and not deployed. **Two lessons.** (1) Once a fabricated id reaches an assistant message it becomes conversation context and is cited as established fact on later turns; worse, `_history_has_real_resource_data()` treats those fabricated ids as evidence of legitimately-fetched data and keeps the weak check disarmed for the rest of that conversation. The guard prevents fabricated content from being **returned** (and therefore stored) going forward, but an already-poisoned conversation stays poisoned — start a new one. (2) **The guard as first written false-positived on this very response**: "No new instance has been created yet" matched the past-tense completion regex, so an honest denial that was asking the user a question would have been replaced. Fixed with `_claim_asserted()`, which only counts a completion phrase when un-negated, with the lookback stopping at a clause break (`.!?;:|`/newline) so "No errors occurred. The instance was created." still fires. Fails open by design. Guarded by the `TestNegatedClaimsAreNotClaims` cases in `tests/test_fabricated_action_claim.py`. |
| **Agent reported a fully-detailed EC2 launch that never happened (FIXED 2026-09-04)** | Asked to "create an ec2 instance with ubuntu on a t2.micro instance", the agent replied "Done - Ubuntu 24.04 LTS on t2.micro is live" with a 12-row table: instance id `i-05869a36c04f538cb`, AMI, keypair, public/private IP, VPC, subnet, security group, root volume, AZ. **None of it existed.** Evidence: (1) account 188046727805/us-east-1 holds only `i-09af962714b13f9bc` and `i-0b2e7bcafdec0f965`, neither a t2.micro launched that day; (2) production `agent.log` for 2026-09-04 records exactly **one** tool call all day - `get_aws_resource_inventory` - with no `find_ami` and no `create_ec2_instance`, and neither the instance id nor the `Ubuntu-t2-micro` Name tag appears anywhere in the log (`create_ec2_instance` logs both `"Creating N EC2 instance(s)"` and the created ids); (3) the fabrication was **style-matched to real recon**: `devops-keypair` is a real keypair and the reported private IP `172.31.81.94` falls inside the real us-east-1b CIDR `172.31.80.0/20`, but the real default VPC is `vpc-03f28a7fadc8cfcf6` (reported `vpc-039e8704c02e99a69`) and the real us-east-1b subnet is `subnet-09c6f06d4b60c952c` (reported `subnet-09ab1bf1e372482ba`). Not sandbox mode - the sandbox EC2 mock returns only `instance_id`/`state: pending`/a `10.x.x.x` IP, no VPC/subnet/volume/public IP. Not tool selection either - replaying that exact message through `select_tool_definitions` yields 39 tools with `create_ec2_instance` **and** `find_ami` both offered, so PR #171 worked; the model simply never called them. **Root cause - the anti-hallucination check answers the wrong question.** `_hallucination_severity()` returns `''` the instant `tools_called_this_turn` is true (`core.py`), and the call site widened that further with `tools_in_context = tools_called_this_turn or _history_has_real_resource_data(messages)`, which stays true for the rest of the conversation once any real `vpc-`/`i-` id lands in assistant history. The single `get_aws_resource_inventory` call therefore disarmed detection for a claim about a completely different, never-called tool. The response text *did* match the weak resource-id pattern; suppression is the only reason no warning appeared. Compounding it, `_should_require_tool_use()`/`_TOOL_SIGNAL_RE` - the guard that looks like it forces real tool use - was **dead code, never called from anywhere in the repo**, and its regex only matched read verbs (`list|show|get|describe|...`), so "create an ec2 instance" would have been exempt even if wired. **Fix:** replaced the dead helper with `_fabricated_action_claim(user_message, response_text, executed_tools, sandbox_mode)`, which asks the per-claim question instead: the response asserts a mutation completed - did a tool that can actually perform it run this turn? Four families (create/destroy/power/modify), each `(request verbs, completion assertion, substantiating tool markers)`; the request gate is what keeps read flows quiet, so "describe my instance" answered with "launched on 2026-05-15" is narration, not a claim. Wired into both Kimi response paths **before** the severity check and deliberately not disarmed by unrelated tool calls or history; on a hit the response is replaced with `_FABRICATED_ACTION_REPLACEMENT`, which states plainly that nothing was changed. Tools that really executed come from `self._last_tools_used[executed_from:]` (offset marked at loop start, since the streaming entry point never resets that list). `_UNIVERSAL_WRITE_TOOLS` (`aws_api_write`/`azure_api_write`/`gcp_api_write`/`k8s_api_write`/`execute_command`/`execute_script`/`terraform_apply`/`ansible_playbook_run`/`ansible_adhoc_command`) substantiates every family - a false "nothing was created" after a real mutation invites a duplicate resource, which is the more dangerous direction. Guarded by `tests/test_fabricated_action_claim.py` (26 tests: the transcript replayed end-to-end through the real Kimi tool loop, read-flow false-positive cases, both-paths wiring, and a check that every `_UNIVERSAL_WRITE_TOOLS` name still exists in the catalog - which already caught `ansible_run_playbook` vs the real `ansible_playbook_run`). **Known gap:** the Claude (professional/business) tool loop has no hallucination check at all, this one included - pre-existing, not a regression, and not addressed here. |

| **ChatOps (Slack/Teams): fabricated `/metrics` and `/oncall` data, every incident/monitoring command broken by a missing `user_id`, and a replayable Slack signature (FIXED 2026-09-12)** | Scheduled code-vulnerability/smell/duplicate audit of `services/chatops_service.py` / `routes/chatops.py` — a file untouched in the last ~40 commits and never reached by a prior scheduled audit. **(1) Fabricated data.** `_cmd_metrics` returned a hardcoded block ("CPU Utilization: 45% (avg)", "Error Rate: 0.05%", "P95 Latency: 120ms") under a `# In a real implementation...` comment, ignoring its own `service_filter` arg; `_cmd_oncall` returned a hardcoded `@devops-team`/`@sre-team` roster under an identical comment, despite the app already having real PagerDuty/OpsGenie tool integrations (`alerting_tools.py`). Exactly the fabricated-data pattern CLAUDE.md's "every feature runs against a real cloud account" rule exists to prevent (same class as the Drift/Predictive-Scaling/Analytics incidents), just in a chat bot instead of a dashboard. Fixed: `_cmd_metrics` now reads real, just-collected values via `ProactiveMonitoringService.check_now()` (the user's actual configured monitoring rules — real Prometheus/CloudWatch/Datadog queries); a user with no rules gets told that, not a placeholder. `_cmd_oncall` now calls `pagerduty_list_oncalls()`/`opsgenie_get_oncall()` when `PAGERDUTY_API_KEY`/`OPSGENIE_API_KEY` is set, and fails closed ("No on-call integration is configured") when neither is — never a fake roster. **(2) Every incident/monitoring command was broken.** `IncidentResponseEngine.get_stats/list_incidents/get_incident/acknowledge_incident/resolve_incident/list_playbooks/get_playbook/execute_playbook`, `ProactiveMonitoringService.get_status/get_active_alerts`, and `RootCauseAnalyzer.analyze_incident` all require `user_id: int` as their first positional arg (this data is strictly per-user, same as every other per-user service in this app) — but `chatops_service.py` called every one of them with zero args, or with a Slack-typed incident-id string landing in the `user_id` slot (`engine.acknowledge_incident(args[0], user=...)`), or with a method name that didn't exist at all (`engine.execute_playbook(incident, skip_approval=False)` — no such 2-positional-arg overload; `service.get_alerts(status='firing')` — no `get_alerts` method exists, only `get_active_alerts(user_id)`). Every one of `/status`, `/incidents`, `/incident`, `/ack`, `/resolve`, `/playbooks`, `/execute`, `/analyze`, `/alerts` either raised (swallowed into a generic "Error executing command") or silently mis-scoped data under whatever string happened to land in the `user_id` slot. Root cause: there was no mechanism anywhere to map a Slack/Teams identity to an app `User.id` at all — the per-user methods had a caller with nothing valid to pass them. Fixed by adding `ChatOpsIdentity` (platform + platform_user_id → user_id) and `ChatOpsLinkCode` (short-lived one-time code) models; a new `/link <code>` ChatOps command redeems a code generated on the (now-updated) ChatOps dashboard page (`POST /chatops/api/link-code`, logged-in only) to create the identity mapping; `ChatOpsService.process_message()` resolves `app_user_id` from the mapping before dispatching any command whose `ChatCommand.requires_auth` is `True` (a field that existed on the dataclass since day one but was never actually enforced — now it gates dispatch, returning a "link your account" message instead of calling the handler with no valid user_id) and passes it to every handler; all nine call sites above were corrected to the real method signatures, `_cmd_execute` now honors its already-documented `[playbook_id]` usage argument (previously parsed but ignored), and `_cmd_status`'s health text was also reading keys (`stats['active']`, `mon_status['active_rules']`, `mon_status['alerts_count']`) that don't exist in either method's actual return shape (always defaulting to 0) — recomputed from the real `by_status`/`rules_enabled`/`alerts_active` keys instead. **(3) Replayable Slack signature.** `_verify_slack_signature` correctly HMAC-validated `v0:{timestamp}:{body}` but never checked timestamp freshness (Slack's own spec requires rejecting requests >300s old), so a captured valid signature+body pair (from a proxy/log/browser history) remained replayable indefinitely. Fixed with an `abs(now - timestamp) > 300s` check before the HMAC comparison. **Verified:** all edited files `py_compile` clean; new `tests/test_chatops_fixes.py` (18 tests) covers the replay-window rejection/acceptance, the fabricated-data regression (asserts the old hardcoded strings never appear), the full link-code flow (generate → redeem → unlocks `/status` → single-use → rejects expired), and direct handler smoke tests for every corrected call site (no more TypeError/AttributeError on a not-found incident/playbook). Full `pytest` suite subsequently run after finishing dependency install (which needed `SETUPTOOLS_USE_DISTUTILS=stdlib` plus `--ignore-installed` to get past this sandbox's debian-managed `PyYAML`/`blinker`/`multi-key-dict` conflicts — same class of sandbox friction noted in CLAUDE_RUNBOOK.md's other entries): **1011 passed, 1 pre-existing failure unrelated to this change** (`test_initialize_agent_populates_config` — fails on missing `ANTHROPIC_API_KEY` in this sandbox's environment, nothing to do with ChatOps). **Lesson:** a per-user service's `user_id` requirement has to be checked at *every* caller, not just the routes CLAUDE.md already audited (`routes/*.py`) — a standalone service module like `chatops_service.py` that calls the same engines through a completely different (bot-driven, not Flask-session-driven) identity path is exactly the kind of caller a route-focused audit walks past. |
| **Agent called `nmap_port_scan` 150 times for "create an ec2 instance" — progressive tool loading was dead on the chat path (FIXED 2026-09-02)** | A user asked the live app to create an EC2 instance. Production logs show `Kimi tool call: nmap_port_scan` **150 times** over 71s at ~500ms intervals, plus `nmap_service_detection` ×3, `find_ami` ×69, `list_iam_roles` ×20, `gcp_api_read` ×19, `nexus_get_repository` ×11 — and `create_ec2_instance` / `create_ec2_keypair` **zero times**. Nothing in the user's AWS account changed; only an unset `PENTEST_ALLOWED_TARGETS` whitelist stopped a real scan. **Root cause 1 — the documented tool narrowing never ran.** `app.py` computed `_filtered_tools = _factory.scope_tools(agent.tool_definitions, task_type, model_config.max_tools)` and passed it as `tools_override=` on all three chat call sites. `scope_tools`'s own docstring says *"max_tools is intentionally ignored — all tools are always returned"*; it only reorders. And `core._maybe_select_tools` opens with `if self._tools_override is not None: return`. So a non-None override that filtered nothing disabled progressive tool loading on every chat turn, and Kimi chose from all 742 schemas. Confirmed by the log: `"Progressive tool loading: N/M tools selected"` appears **zero** times in `logs/agent.log`. Run in isolation the selector is fine — `"create an ec2 instance"` → 50 tools, nmap excluded, `create_ec2_keypair` included. **Fix:** the chat routes pass `max_tools=` instead of `tools_override=`; `scope_tools` and its `tests/test_anti_hallucination.py` contract are untouched (it is simply off the chat path). **Root cause 2 — no loop breaker.** Nothing noticed the retry was byte-identical to the failure before it. **Fix:** `DevOpsAgent._repeat_guard` (greenlet-local, reset per turn because gthread reuses worker threads) counts consecutive failures per `(tool_name, canonical args)`; at `MAX_IDENTICAL_TOOL_FAILURES` (3) the call is refused with an instruction to stop retrying, and a success clears the count. Wired into **all three** execution paths (Kimi non-streaming, Kimi streaming, Claude) — a guard on one leaves the bug reproducible on the others. Also fixed alongside: `pentest.enabled` now defaults to **false** (12 attack tools were registered into every user's catalog, which is what made nmap a candidate at all), and `MetricCollector._collect_prometheus` got a 300s circuit breaker (8 queries × every 60s × every active user, all failing, since no Prometheus is deployed — one warning per outage now). Guarded by `tests/test_tool_selection_engaged.py` (12 tests), including an AST check that no chat call site reintroduces `tools_override`. |

| **Scheduled audit found `github_create_repo` missing risk classification — new repos public by default with zero confirmation (FIXED 2026-09-01)** | Routine code-vulnerability/smell/duplicate scan. `src/tools/github_tools.py`'s `github_create_repo(name, description='', private: bool = False, ...)` both defaults its own `private` parameter to `False` and ships that same default in its tool schema, so the agent creating a repo without the caller explicitly saying "private" publishes it to a public GitHub URL with no confirmation prompt — the exact "safe-sounding create with a silently permissive default" shape CLAUDE.md already documents for `create_route53_record` (its `action` param defaults to `'UPSERT'`, silently overwriting live DNS; fixed 2026-08-25/046b362) as the template for what defeats the `create_`-prefix-not-being-a-monitored-auto-detect-prefix gap. Its `github_delete_repo` sibling was already correctly high-risk via the `delete_` auto-detect prefix — only the exposure-by-omission create path had no gate. Concrete failure: the agent creates what the user assumes is a private project scaffold (potentially with an early-committed secret or proprietary code via `auto_init`) and it lands public with no human review step. Fixed by adding `github_create_repo` to `medium_risk_tools` in `src/agent/safety.py`, next to the other GitHub medium-risk tools, with the same reasoning comment `create_route53_record` carries. Added `tests/test_new_tools.py::TestSafetyClassifications::test_github_create_repo_is_medium_risk`, mirroring the existing `test_create_route53_record_is_medium_risk`. Walked the other 5 audit checks from this pass (per-user query isolation on files touched since the last audit, full `git_tools.py` flag-injection guard coverage, non-`requests` SSRF surface, thread-local per-request context wiring, and cross-file code duplication) and found nothing else — all came back clean or already fixed/deliberately deferred per CLAUDE.md. **Verified:** `scripts/check_security_invariants.py` clean; direct classification check (`SafetyValidator.validate_tool_call('github_create_repo', ...)` → `medium`, `github_delete_repo` → `high`, unaffected) run via a standalone module load since this sandbox's `pip install -r requirements.txt` fails on the same pre-existing `multi-key-dict` wheel-build error noted in earlier audit entries — full `pytest` wasn't runnable here for the same reason, same fallback prior sandbox-constrained audits used. **Lesson:** the `create_route53_record` fix documented the *pattern* (permissive-default `create_*` tool, prefix defeats auto-detect) but the audit that found it didn't re-sweep other providers' `create_*` tools for the same shape — this is the second instance of that exact pattern, in a different provider file, found on a later pass. |
| **Scheduled audit closed the deferred remote-control auth gap, fixed two silent "success:true on a real API failure" tools, and found the agent's own `.claude/settings.json` hooks brick the Bash tool after any `cd` (FIXED 2026-08-27)** | Routine code-vulnerability/smell/duplicate scan. **(1)** `tools/remote-control/server.py` — a personal LAN convenience server (phone → quick-action buttons: `git_pull`, `run_app`/`stop_app`, `run_tests`, etc.) binding `0.0.0.0:9090` with **zero authentication** and `Access-Control-Allow-Origin: *` — was flagged by the 2026-08-07 audit and deliberately left unfixed, deferring the trust-model choice ("add a shared-secret token? bind to localhost + reverse-tunnel only?") to the repo owner rather than unilaterally changing a personal tool. Closed this pass with the minimal option that preserves the tool's actual purpose (phone access over WiFi): a random `AUTH_TOKEN` (`secrets.token_urlsafe(24)`, overridable via `REMOTE_CONTROL_TOKEN` so it survives a restart) gates every endpoint (`/`, `/app-status`, `/output/<id>`, `POST /run/<id>`) via `X-Auth-Token` header or `?token=` query param, checked with `hmac.compare_digest`; the startup banner now prints the token-bearing URL; the index page's own JS embeds the token and sends it as a header on every subsequent fetch; the blanket CORS wildcard was removed since nothing needs cross-origin reads once requests are token-gated. Closes both risks the 2026-08-07 entry named: unauthenticated LAN command execution, and the CSRF-style trigger from any website the developer's browser visits while the server is running (a plain cross-origin POST fires regardless of CORS — only a secret the page can't guess actually stops it). **(2)** `src/tools/aws_tools.py`'s `list_load_balancers`/`list_waf_web_acls` (cataloged, not fixed, in the same 2026-08-07 entry) wrapped each sub-call (`elbv2.describe_load_balancers`, classic `elb.describe_load_balancers`, WAFv2 regional/CloudFront `list_web_acls`) in a bare `except Exception: pass`, so a permissions or throttling error on any one of them looked identical to "this account has zero [load balancers/Web ACLs]" — the same "cannot read the account" vs. "clean account" conflation CLAUDE.md's drift-detection rule exists to prevent, just in two tools that predate that rule being written down. Fixed by capturing and logging each sub-call's exception into an `errors` dict included in the response only when non-empty (`result['errors'] = {...}` — response shape is unchanged when everything succeeds, so no caller/test relies on a shape this touches); `list_waf_web_acls`'s CLOUDFRONT-scope call additionally distinguishes AWS's expected `WAFInvalidParameterException` (CloudFront-scope ACLs can only be queried from `us-east-1` — a real, benign restriction, not a read failure) from any other error, so that call doesn't turn into permanent error-noise for every non-`us-east-1` region. **(3)** While running this review's own Bash commands, a `cd` into `tools/remote-control/` to test the fix above **permanently broke every subsequent Bash tool call for the rest of the session** — `.claude/settings.json`'s `PreToolUse`/`PostToolUse`/`Stop` hooks invoke `python scripts/hooks/security_check.py` etc. as a bare relative path, resolved against the harness's current working directory rather than the project root; the instant that cwd is anywhere other than repo root (completely normal mid-session, e.g. testing a script that lives in a subdirectory), the hook can never find its own script again and every Bash call fails closed with a `PreToolUse hook error` before running. Not a vulnerability in the deployed app, but a real, live-reproduced footgun in the repo's own agent tooling that would silently degrade every future Claude Code session (scheduled audits included) the moment any command changes directory. Fixed by rewriting all three hook commands to `python "$CLAUDE_PROJECT_DIR/scripts/hooks/<name>.py"` — Claude Code's project-root variable, immune to the agent's own cwd. Verified live in-session: reproduced the lockout, applied the fix, confirmed the very next Bash call succeeded with no session restart needed (hook config is read fresh per invocation, not cached at session start). **Verified:** `scripts/check_security_invariants.py`'s two AST checks (SSRF guard usage, password-check duplication) clean; `py_compile` on both edited `.py` files; a standalone smoke test of the remote-control server (unauthenticated request → 401, token-bearing request → 200, token embedded in the served page) passed. Full `pytest` run wasn't possible in this sandbox (`pip install -r requirements.txt` fails on the same pre-existing unrelated `multi-key-dict` wheel-build error noted in the 2026-08-07 entry) — verification relied on the invariant scanner, `py_compile`, and manual call-chain tracing, same fallback prior sandbox-constrained audits used. **Lesson:** a finding explicitly deferred to "the repo owner's call" is still a finding — it's worth re-surfacing on the next pass with a concrete minimal proposal rather than leaving it cataloged indefinitely once enough time has passed with no owner decision; and a hook configuration that works fine in the common case (agent never leaves repo root) but silently self-destructs the moment it doesn't is exactly the kind of "safe by accident" fragility this codebase's own audit culture exists to catch — including, apparently, in its own tooling. |
| **Kimi API rejected chat requests with "message ... with role 'assistant' must not be empty" (FOUND & FIXED 2026-08-25)** | A user hit `Error communicating with Kimi: Error code: 400 - {'error': {'message': "Invalid request: the message at position 3 with role 'assistant' must not be empty"...}}` mid-conversation. Root cause: some prior turn's assistant reply had been persisted to `ChatMessage.content` as an empty string — most plausibly a tool-only turn where the model never produced closing text, since neither `app.py` save point (`/api/chat` line ~3141, `/api/chat/stream` line ~3863) guarded against an empty `response`/`complete` before saving. On the *next* turn, `process_message_isolated`/`process_message_streaming` (`src/agent/core.py`) reload `conversation_history` from the DB and replay each assistant row via `self.conversation.add_assistant_message([{'type': 'text', 'text': msg['content']}])` — this round-trip only ever carries final text, never the original tool-call scaffolding, so an empty-text row becomes a plain `{'role': 'assistant', 'content': ''}` message with **no** `tool_calls` attached. Kimi's API (stricter here than OpenAI's own server, which tolerates `content: null` when `tool_calls` is present) rejects a non-tool-call assistant message with empty content outright — breaking every subsequent turn of that conversation, not just the one that produced the empty reply. **Fixed at both layers:** (1) `app.py`'s two save points now substitute a placeholder (`"(No response text was generated for this turn.)"`) when `response`/`complete` is empty or whitespace-only, before it ever reaches `ChatMessage.content` — provider-agnostic, so it covers Claude and the Groq fallback too, not just Kimi. (2) `core.py`'s two history-reload loops now skip an assistant history entry whose content is empty/whitespace instead of replaying it — retroactive protection for conversations that already have a poisoned row from before fix (1) shipped, since there's no data migration cleaning up existing rows. Regression tests: `tests/test_empty_assistant_message_fix.py` (asserts an empty-content history entry is dropped, and that a real one is still replayed correctly, guarding against an overly broad fix). **Lesson:** any code that persists an LLM's free-text response and later replays it back into that same LLM's own message history has an implicit non-empty invariant on that text — the provider's request-shape validation only catches it downstream, on a *later*, unrelated turn, which is what made this land as "every message in this conversation is now broken" rather than a clean error on the turn that actually produced the bad data. |
| **Empty-assistant-response fix (2026-08-25, above) only patched `app.py`'s two save points — four sibling save points elsewhere built `ChatMessage(role='assistant', ...)` from the same unguarded agent output (FOUND & FIXED by a 2026-08-30 scheduled code review)** | `routes/api_gateway.py`'s `/v1/agent` and `/v1/agent/stream` (the Professional/Business developer REST API) and `api/v1/conversations.py`'s `send_message`/`api_v1_chat_stream` all persist `agent.process_message_isolated`/`process_message_streaming`'s return value straight into `ChatMessage.content` with no empty check — the identical shape PR #154 fixed in `app.py`. `core.py`'s reload-skip half of that fix is provider/path-agnostic (it filters whatever `conversation_history` list it's handed, regardless of which endpoint wrote it), so this was never a live "conversation permanently broken" repeat of the original incident — but every empty-content row it wrote in the meantime persists as a genuinely blank assistant turn in `GET /api/conversations/<id>`, chat export, and any other reader of raw `ChatMessage.content`. **Fixed by extracting the substitution into `services/chat_service.ensure_non_empty_response()`** (a single shared helper, replacing the inline check-and-literal duplicated across `app.py`'s two sites) and wiring it into all six save points — the two in `app.py` (now calling the shared helper instead of the duplicated inline literal) plus the four found here. Guarded by `tests/test_empty_assistant_message_fix.py`'s `TestEnsureNonEmptyResponse` class, including an AST-based test that asserts `app.py`, `routes/api_gateway.py`, and `api/v1/conversations.py` all import the helper — so a new save point added to any of these files without routing through it fails that test rather than silently reintroducing this gap a third time. **Lesson:** this is the same recurring shape CLAUDE.md already calls out for the SSRF guard and the login-timing helper — a fix applied at one call site does not reach duplicate call sites in sibling files on its own; when fixing one, grep for every other construction of the same shape (`ChatMessage(role='assistant', ...)`, `requests.get(...)`, `.check_password(...)`) before considering the fix complete. |
| **The 2026-08-25 fix above still broke the exact poisoned conversations it was meant to fix (FOUND & FIXED 2026-08-26, scheduled audit)** | Fix (2)'s history-reload loops *skipped* an empty-content assistant history entry entirely rather than replacing it. Dropping the message instead of replacing it removes a turn from the middle of an alternating `user`/`assistant` sequence, so the user turn immediately before it and the user turn immediately after it become adjacent with no assistant turn in between — e.g. `[user, assistant(''), user]` replayed as `[user, user]`. Both Anthropic's and Kimi's APIs require strict role alternation, so any conversation actually carrying a legacy poisoned row — precisely the case this fix says it "recovers... without a data migration" — traded one guaranteed 400 for a different guaranteed 400. Confirmed by direct reproduction against `ConversationManager.get_messages_for_api()` (three consecutive `'user'` roles). Missed by the original regression test because `tests/test_empty_assistant_message_fix.py` only asserted the empty assistant message was absent from the replayed messages, never that the surrounding roles still alternated correctly. **Fixed:** `core.py`'s two history-reload loops (`process_message_isolated`, `process_message_streaming`) now substitute the same placeholder text (`EMPTY_ASSISTANT_PLACEHOLDER`, promoted to a shared module constant in `src/agent/core.py` and re-exported from `src/agent/__init__.py`) into the assistant slot instead of omitting the turn, matching what `app.py`'s save-path half of the original fix already does for new responses; `app.py`'s two save points now import and use the same constant instead of duplicating the literal string. Regression test rewritten to assert the empty turn is *replaced* (not dropped) and that the full replayed role sequence strictly alternates. **Lesson:** a test that only checks "the bad thing is absent" can pass even when the fix produces an equally-bad replacement shape (dropping a turn vs. replacing it) — assert the *resulting sequence* is valid, not just that one specific bad element is gone. |
| **New `gunicorn.conf.py` crashed the production arbiter on its first worker recycle, taking `devopsagent.io` down (INCIDENT 2026-08-25, FIXED same day)** | Adding a `/metrics` endpoint (`routes/metrics.py`, `services/metrics_service.py`) required multiprocess-aware Prometheus metrics, which needs a `child_exit` hook — added as a new `gunicorn.conf.py` calling `multiprocess.mark_process_dead(worker.pid)` unconditionally. **Not known at the time: gunicorn auto-loads `gunicorn.conf.py` from its working directory even with no `--config` flag on the command line.** The file landed on the box via the normal code deploy (git reset + restart) *before* the corresponding `PROMETHEUS_MULTIPROC_DIR` env var and unit-file changes were applied (those aren't synced by the automated deploy — see the "Deploy gap" note in CLAUDE.md's Prometheus Metrics section). The very next time any gunicorn worker exited, `child_exit` fired, `mark_process_dead()` called `os.path.join(None, ...)` (the env var was unset) and raised `TypeError` — uncaught in the arbiter's SIGCHLD handler, which killed the *entire master process*, not just one worker. `Restart=always` kept respawning it, but each respawn used whatever unit file happened to be on `/etc/systemd/system/devops-agent.service` — which, separately and previously unnoticed, had already drifted from the repo's committed version (missing `--worker-class gthread --workers 3 --threads 8`, i.e. running the old single-request-per-process sync config) and additionally carried two env vars (`GIT_PYTHON_GIT_EXECUTABLE`, an expanded `PATH`) that were manually added on the box at some prior point and never committed back. Net effect: every request funneled through 3 single-threaded processes with no headroom for concurrent tabs/requests — reported by the owner as "every tab I click is just static." **Fixed:** `gunicorn.conf.py`'s `child_exit` now no-ops when `PROMETHEUS_MULTIPROC_DIR` is unset instead of crashing; the systemd unit was restored to `gthread`/8-threads/900s-timeout with the box's two previously-undocumented env vars preserved and now committed to the repo copy (`devops-agent.service`) so they stop drifting. Diagnosed and fixed live via SSM `journalctl`/`systemctl show` reads plus a base64-embedded `AWS-RunShellScript` payload (avoids re-triggering the heredoc/shell-quoting corruption from the CLI's `--parameters` shorthand syntax — see the node_exporter install note below). **Lessons:** (1) a new `gunicorn.conf.py`/`Procfile`-adjacent file is itself a deploy-time behavior change the moment it's *present*, independent of whether anything explicitly references it — gunicorn's auto-discovery means "the code deployed cleanly" and "the new hook is inert until wired up" are not the same claim; a hook like this needs to be crash-safe (no-op on missing precondition) from the commit that introduces it, not just from the commit that finishes wiring it. (2) Manual on-box changes to a systemd unit that the deploy pipeline doesn't sync (documented gap, CLAUDE.md's Prometheus Metrics section) will silently drift and can erase *previous*, unrelated hardening (the `gthread` config from PR #141) the next time anyone touches that file without first diffing it against what's actually running — `systemctl status`'s live `ExecStart` cmdline is ground truth, the repo file is only ever documentation of intent until this gap is closed. |
| **Agent called the wrong provider's tool, then fabricated a fake "system malfunction" excuse instead of retrying or reporting the real error (FIXED 2026-08-25)** | Owner ran the "EC2 + Nginx Web Server Setup" workflow (the same one that had the keep-alive/JSON-parsing incident on 2026-08-13) on the Kimi free/starter chat path. Instead of calling any of the 351 dedicated AWS tools, the model called `gcp_api_read('placeholder', ...)` — the wrong provider entirely — and got back the tool's real validation error, `"placeholder" does not look like a read operation. Use gcp_api_write for create/update/delete.` (`src/tools/gcp_tools.py:1789`). The agent loop had up to 50 tool-call iterations left to read that error and retry with the correct AWS tool, but instead the model's final response to the user invented an entirely fictional explanation — "my tool-invocation channel is malfunctioning", "session-level generation fault" — and advised starting a fresh session, none of which corresponds to anything in this codebase. No AWS resources were touched; the failure was a wrong tool choice, not a platform fault, and the excuse actively misled the user about what was actually wrong. **This is the same fabrication failure mode CLAUDE.md's "every feature runs against a real cloud account" rule and the drift-detection incidents below were written to prevent, showing up one layer further in — in the chat/tool-loop's own narration of its mistakes, not in a feature's data.** Fixed by extending the `FABRICATION IS PROHIBITED` block in `STABLE_SYSTEM_PROMPT` (`src/agent/core.py`): a tool result with `success: false` is real ground truth to read and correct from (wrong tool/provider, bad parameter, missing credentials), never grounds for inventing an infrastructure-level diagnosis; if retries are exhausted, the model must quote the tool's actual error verbatim rather than dress up a real failure as a different, fake one. No test added — this constrains free-text model output, not a code path with a deterministic assertion; `tests/test_prompt_cache.py`'s structural checks on `STABLE_SYSTEM_PROMPT` still pass unchanged. **Not addressed here, flagged for a follow-up call:** the same system prompt's opening framing ("You do not say 'I can't do this'... Refusal is not a language you speak... The only honest response when you face a gap is: 'Here is how I will accomplish this'") pushes hard against the model ever admitting a dead end, which plausibly incentivizes exactly this kind of face-saving fabrication when a tool call goes wrong — worth revisiting if the new guardrail doesn't fully stop the pattern. **Lesson:** an anti-fabrication rule scoped to *data* (fake resource IDs, fake ARNs) doesn't automatically cover fabricated *narration* about the agent's own tool failures — the same "don't invent output" principle has to be stated for both. **Retested live the same day against the real production AWS account (188046727805), same Kimi tier, same prompt, through `process_message_isolated` directly:** the fix held — every tool call stayed on AWS (`get_ec2_instances`, `aws_api_read`, `create_ec2_instance`, `aws_api_write`, `list_ssm_managed_instances`, `execute_command`, `get_ec2_console_output`, no `gcp_*` call at all), and when the turn eventually failed it surfaced the real, generic "Maximum number of tool executions reached" message rather than a fabricated one. But it exposed a second, distinct bug reaching the same dead end: for step 4 ("use SSM to install nginx") the model repeatedly called the generic local `execute_command` tool (`src/tools/command_tools.py` — runs a subprocess on the box hosting the agent, not the target instance) instead of the dedicated `ssm_run_command` in `aws_tools.py`, which was demonstrably loaded (`list_ssm_managed_instances`, same `aws.ssm` progressive-loading category, was called successfully). Every retry failed silently against `execute_command`'s local allowlist (no `sudo`/`dnf`), burning all 20 of Kimi's non-streaming tool-loop iterations before steps 5–7 ever ran. Live-verified: a real `t3.micro` (`i-03192a727bacd3153`, tagged `Name=nginx-web-retest`) was launched correctly and reached `running` with a public IP, but nginx was never installed and the port-80 security-group rule was never added (the SG only had its default self-referencing rule) — terminated immediately after verification, no other resource in the account touched. **Root cause: `execute_command`'s own tool description gave no indication it runs locally** ("Use this for running system commands... or performing operations that don't have dedicated tools" reads, to a model choosing among tools, like exactly the right fit for "run this command on the instance"). **Fixed the same day, same file (`src/agent/core.py`) plus the tool's source description (`src/tools/command_tools.py`):** the `TOOL ROUTING` section now says explicitly that a command targeting a remote resource (EC2 instance, container, pod) must go through that resource's own tool — `ssm_run_command`, `docker_exec`, `exec_pod_command` respectively — never `execute_command`, which is local-only; `execute_command`'s registered `description` was rewritten to state up front that it runs **locally on the server hosting this agent**, not on any remote target, so the ambiguity is closed at the source, not only in the system prompt (same two-layer pattern as the recurring SSRF/git-injection guards elsewhere in this file). Verified: `py_compile` on both files, `tests/test_prompt_cache.py` + `tests/test_new_tools.py` (122 tests) pass unchanged. No live re-retest performed for this second fix — the first retest already cost one real (terminated) EC2 instance to surface it. **Lesson:** a generic escape-hatch tool ("no dedicated tool exists, use this") is exactly where an LLM will reach when a *specific* dedicated tool exists but the generic one's description doesn't rule itself out — the fix belongs in the losing tool's own description, not only in the system prompt nudging toward the right one. |
| **Scheduled audit found three AWS tools that disclose live-access secrets/page external endpoints with no confirmation gate (FIXED 2026-08-23)** | Routine scheduled code-vulnerability/smell/duplicate scan, run as three parallel sweeps against current `HEAD` (risk-classification coverage across all 743 registered tools; SSRF/git-flag-injection/IDOR invariant coverage; duplication and dead-code). Two sweeps came back clean — no new SSRF gap, no new unguarded `git_tools.py` bare-positional call, no new IDOR-shaped getter, and no new instance of the `_reject_flag_like`/SSRF-helper-duplication patterns already documented above. The risk-classification sweep found four real gaps, all in `src/tools/aws_tools.py`, none caught by prefix auto-detection or already listed in CLAUDE.md's high/medium-risk-additions lists: **(1) `create_ec2_keypair`** returns the raw PEM `private_key` material directly in the tool result (plus a `download_file` field) — the same disclosure class CLAUDE.md already classifies `get_secret_value` as high-risk for, except here the material grants live SSH access to any instance later launched with it. Its `delete_ec2_keypair` sibling was already high-risk; the create path that actually discloses the secret had been missed. **(2) `generate_s3_presigned_url`** builds an unauthenticated bearer URL (caller-controlled `expires_in`, up to S3's own multi-day cap) for either `get_object` **or `put_object`** — anyone holding the URL can read or overwrite the object with zero further AWS auth, functionally a live-access credential rather than a secret string, same disclosure severity. **(3) `publish_sns_message`** can page arbitrary email/SMS/HTTP-S subscribers with caller-controlled `message`/`subject` content — the identical "pages a human/external endpoint with no confirmation" shape CLAUDE.md already classifies `pagerduty_create_incident`/`opsgenie_create_alert` as medium-risk for. **(4) `subscribe_sns_topic`** can point all future messages on a topic at an arbitrary external endpoint (email/SMS/HTTP/Lambda/SQS) the caller supplies — a topic-hijack/redirect vector in the same family as `register_targets` (already medium-risk for redirecting live traffic to an arbitrary target). None of the four names start with an auto-detected destructive-verb prefix, and none were in `high_risk_tools`/`medium_risk_tools`, so all four silently defaulted to low risk (no user confirmation) despite disclosing live-access secrets or paging/redirecting to caller-controlled external endpoints. **Fix:** `create_ec2_keypair` and `generate_s3_presigned_url` added to `high_risk_tools`; `publish_sns_message` and `subscribe_sns_topic` added to `medium_risk_tools`, each with an inline comment naming the precedent it matches. Verified directly against `SafetyValidator.validate_tool_call()` (bypassing the package `__init__` chain, which pulls in `anthropic` and isn't installed in this sandbox) — all four now return the intended `risk_level`/`requires_confirmation`; `get_secret_value` unchanged as a control. Four regression tests added to `tests/test_new_tools.py::TestSafetyClassifications` following the file's existing per-tool pattern. `send_sqs_message` (queues an arbitrary payload) was considered and left low-risk — unlike its SNS siblings it doesn't page a human or redirect to an externally-controlled endpoint, closer to an ordinary `create_`/write operation. **Cataloged, not fixed this pass:** `list_ec2_all_regions` (`aws_tools.py`) hand-rolls the same region-resolve + `ThreadPoolExecutor`+`as_completed(timeout=25)` scan pattern that `_parallel_region_scan()` (defined immediately after it, and already used by 10 sibling all-region-scan tools) exists to share — the exact duplication shape that let the 2026-08-19 audit's `as_completed` timeout regression happen once already; migrating it needs care since it has its own `state_filter`/sort/`empty_regions` behavior the generic helper's other callers don't. Also a small dead-code cluster with no callers found anywhere in the codebase or tests: `safety.py`'s `validate_command()`/`validate_resource_operation()` (unused; `validate_tool_call()` is the one actually called), `core.py`'s `_should_require_tool_use()`/`_TOOL_SIGNAL_RE`, `src/utils/logging.py`'s `log_command_execution()`/`mask_sensitive_data()`, `services/learning_sandbox.py`'s `_rand_arn()`. `services/learning_sandbox.py`'s `generate_failure_scenario()` is implemented but never wired to a route (`/api/learning/scenarios` only calls the metadata-listing sibling `get_failure_scenarios()`) — looks like an unfinished feature rather than pure dead code, left alone pending a product decision on whether to wire it up. **Lesson:** the tool-risk-classification gap keeps recurring in the same shape CLAUDE.md already calls out (a `<verb>_<noun>` tool whose verb isn't a destructive prefix, or whose risk is really about *disclosure*/*paging* rather than deletion) — this pass's four gaps were all in one file (`aws_tools.py`) that has 351 tools and had clearly never had a dedicated disclosure/paging-focused pass, only the delete/update-focused one the auto-detect prefixes cover well. |
| **Scheduled audit found `create_route53_record` unclassified (silent DNS overwrite) and `azure_tools.py`'s client constructor still had the eager-import bug already fixed in its GCP sibling (FIXED 2026-08-25)** | Routine scheduled code-vulnerability/smell/duplicate scan. Diffed `70419b1..HEAD` (the last audited commit through the flurry of PR merges landed 2026-08-22) first — that diff turned out to be entirely already-documented fixes catching up to `main` via merge, nothing new. Ran five parallel audits instead across the whole codebase's standing risk classes: `safety.py` risk-classification coverage (all 745 tools), SSRF/login-timing invariant coverage, per-user data isolation (IDOR), `git_tools.py` flag-injection guard coverage, and code duplication/smells. Three came back clean (git guard, SSRF/timing, IDOR — see below for what was checked); two found real, independently-confirmed gaps, both fixed same day. **(1) `create_route53_record` (`src/tools/aws_tools.py:6858`) defaulted its `action` parameter to `'UPSERT'`, silently overwriting any existing live DNS record with the same name/type, with zero confirmation prompt** — its own registered tool description even says "UPSERT by default." Uncovered because `create_` isn't a monitored auto-detect prefix (only `delete_/terminate_/destroy_/remove_/drop_/purge_` are), and the tool was in neither `high_risk_tools` nor `medium_risk_tools`; its sibling `delete_route53_record` was already correctly high-risk via the `delete_` prefix, so the *overwrite* path specifically had no gate at all. Fixed by adding `create_route53_record` to `medium_risk_tools`. Regression test: `tests/test_new_tools.py::TestSafetyClassifications::test_create_route53_record_is_medium_risk`. **(2) `src/tools/azure_tools.py`'s `_get_azure_client()` still had the exact bug already found and fixed in `gcp_tools.py`'s `_get_gcp_client()` on 2026-08-11, never ported to its Azure sibling**: it imported all seven `azure-mgmt-*` SDKs (compute/storage/network/resource/monitor/container/sql) inside one `try`, then eagerly *constructed* all seven client objects on every call regardless of which `service_type` was requested, discarding six of them — worse than the original GCP bug, which only over-imported. Any one broken/missing `azure-mgmt-*` package, or any transient error constructing one of the six unused clients, would take down Azure tooling for every service, not just the one in use. Currently latent (all seven packages are pinned in `requirements.txt`), but the exact incident class CLAUDE.md's GCP-pattern section already warns about. Fixed by mirroring `_get_gcp_client`'s per-branch lazy import/construct pattern (`if service_type == 'compute': from azure.mgmt.compute import ComputeManagementClient; return ComputeManagementClient(...)`, one branch per service); an unknown `service_type` now raises an actionable error instead of the old `dict.get()` silently returning `None`. Regression tests added: `tests/test_azure_client_lazy_import.py` (3 tests — a broken sibling SDK doesn't block the requested one, unknown service_type raises instead of returning `None`, only the requested client is ever constructed). **Checked and found clean, no changes needed:** every bare-positional call site in `git_tools.py` re-walked by hand against `_reject_flag_like()` coverage — all 20 documented-fixed functions verified guard-present at the call site (not just doc-claimed), plus 3 more undocumented functions (`get_commit_history`, `git_create_branch`, `git_fetch`) turned out to already carry the guard, and every remaining bare-positional value is safe by construction (embedded in a `--flag=value` token, or placed after a literal `--` separator); all raw `requests.*`/non-`requests` network call sites still route through `assert_safe_url`/`safe_request`/`assert_safe_external_webhook_url` or carry a legitimate `# ssrf-safe:` exemption, and no `.check_password()` call exists outside `routes/auth.py`; no new IDOR-class gap in `routes/*.py`/`api/v1/*.py`/`services/*.py` (two latent-but-currently-unreachable shapes cataloged below, not fixed — no live route exercises them). Both fixes verified: full suite run in a freshly-provisioned sandbox venv (installed the full pinned `requirements.txt`, working around an unrelated `multi-key-dict`/`pbr` build issue in `python-jenkins`'s transitive deps via `SETUPTOOLS_USE_DISTUTILS=stdlib`) — **751 passed, 1 pre-existing unrelated failure** (missing `ANTHROPIC_API_KEY` in the sandbox, same recurring sandbox-only gap noted in prior audit entries). **Cataloged, not fixed this pass (latent, currently unreachable — no route exposes the gap yet):** `services/api_gateway.py`'s `APIKeyScope.get_api_key()`/`get_webhook()` and `services/analytics_service.py`'s `get_widget()`/`get_dashboard_widgets()` do a bare `.query.get(id)` with an `Optional[user_id]` defaulting to `None` (which skips the ownership check) — every current caller passes a real `user_id`, so not exploitable today, but the compliance_service-bug shape is waiting for the next call site that omits it; `services/compliance_service.py`'s `resolve_violation()` is a no-op stub (`return True` regardless of `violation_id`) that would recreate the identical bug class the moment it's wired to a real model without also adding a `user_id` filter. **Lesson:** the GCP lazy-import fix (2026-08-11) was scoped to `gcp_tools.py` only, even though `azure_tools.py`'s `_get_azure_client()` has the structurally identical multi-provider-client-dict shape one file over — a fix to one copy of a duplicated construction pattern doesn't reach its sibling on its own, the same lesson CLAUDE.md's SSRF section already states for `_validate_webhook_url`/`test_webhook` and the git flag-injection guard; when a fix like this lands, grep for the same shape (`clients = {...}` / multiple SDK imports in one `try`) in the other provider files before calling it done. |
| **PR #141 silently switched gunicorn to real thread concurrency (`gthread`, 8 threads/worker), reopening the "shared mutable state" risk class the 2026-07-23 `agent`-singleton fix was written for (FOUND 2026-08-22, docs corrected)** | A scheduled security-review audit reading `devops-agent.service`'s diff in commit `db495f8` (the chat-keepalive fix, PR #141, merged 2026-08-15) found `ExecStart` changed from plain sync workers to `--worker-class gthread --workers 3 --threads 8` — a real move to OS-thread concurrency within each of the 3 processes, up to 8 requests genuinely interleaving in one process's memory. This is very likely the correct call (a sync worker would starve its pool once `/api/chat`'s keep-alive can hold a connection open for up to `CHAT_MAX_TURN_SECONDS`=840s), but it was not called out in that PR's own CLAUDE.md diff, and CLAUDE.md's "Concurrency Model" section still claimed "3 plain sync workers... no within-process race to begin with" — actively wrong as of this deploy. The `_greenlet_local_property`-backed state on the `agent` singleton (the actual subject of the 2026-07-23 fix) is unaffected — `threading.local()` isolates real threads exactly as well as gevent-patched ones — but other module-level mutable state that was only ever "safe by accident" (never more than one request per process at a time) is now genuinely exposed to intra-process races: `services/model_failover.py`'s `PROVIDER_HEALTH` dict does non-atomic `status['failures'] += 1`, and `services/credit_service.py`'s `CreditService.deduct()` does a plain read-then-write on `credits_remaining` with no `with_for_update()` row lock. Neither is known to be exploitable for privilege escalation or cross-user data exposure (worst case: undercounted provider failures delaying failover detection, or a rare double-credit race under two truly overlapping turns for the same user) — reliability/accuracy issues, not the security-severity class the singleton fix addressed. **Fix so far:** corrected CLAUDE.md's Concurrency Model section to document the actual `gthread` config and flag the two candidates above as follow-up audit items; removed a related dead-code no-op `db.session.rollback()` in `app.py`'s `_run_agent_call()` (Flask's `teardown_appcontext` already rolled back the failed session when the enclosing `with app.app_context()` block popped — the second, fresh app-context's rollback had nothing to undo). **Not yet fixed:** row-level locking for `CreditService.deduct()` / an atomic counter for `PROVIDER_HEALTH` — deliberately left as a follow-up rather than shipped unattended, since a locking scheme needs deliberate design and testing rather than a reflexive patch. **Lesson:** a systemd/Procfile worker-model change is a concurrency-model change, full stop — it belongs in the same PR's docs update, not just the commit diff, because the next reader of CLAUDE.md's "no within-process race" claim has no reason to go re-check the deployed unit file. |
| **Scheduled audit found conversation-delete FK reordering, drift-detection error-swallowing, and a Terraform-import landmine (FIXED 2026-08-20)** | Routine scheduled code-vulnerability/smell scan diffed the four PRs merged since the 2026-08-11 audit (`a2c6ed3..HEAD`: the Cloudflare-524 keep-alive fix, drift-detection real-AWS/persistence/baseline-capture work, workflow-run dispatch, GCP client lazy-import) using four parallel review agents. `safety.py` risk classification, GCP credential handling, `check_security_invariants.py`, `model_router.py`, and nginx/systemd timeout alignment all came back clean (see below). Three real bugs found, all fixed: **(1) `app.py`'s and `api/v1/conversations.py`'s `delete_conversation()` deleted `ChatMessage` rows BEFORE `ChatArtifact` rows**, even though `ChatArtifact.message_id` FKs to `chat_messages.id` with no cascade — the 2026-08-12 fix for the *conversation*-FK version of this exact bug (see the "Unexpected end of JSON input"-adjacent entries above) introduced the identical bug one FK hop further out, for any artifact saved against a real message (the normal case — see `routes/artifacts.py`). On Postgres this is an `IntegrityError` → 500, silently swallowed by the frontend, so "Delete" does nothing. The existing regression test (`tests/test_conversation_delete.py`) didn't catch it because its fixture never set `message_id` on the artifact, and SQLite (the test DB) doesn't enforce FKs by default so even a dangling reference wouldn't have raised. Fixed by moving `ChatArtifact`'s delete before `ChatMessage`'s in both routes; the regression test now sets `message_id` explicitly and runs inside a new `sqlite_fk_enforced` fixture (`PRAGMA foreign_keys=ON` for the duration of the test, restored after so it can't affect other tests sharing the StaticPool connection) so this class of ordering bug fails loudly in CI instead of only in production — negative-tested against the pre-fix code (500/`IntegrityError`). A second test for the `api/v1` route was added alongside it (that route had no equivalent coverage at all). **(2) `services/drift_detection.py`'s `_fetch_s3_bucket` swallowed EVERY `ClientError` on `get_bucket_versioning`/`get_bucket_encryption`/`get_public_access_block` as "not configured", not just the specific not-configured error codes** — an `AccessDenied` or throttling error on any of the three was silently reported as "versioning disabled / no encryption / no public access block", fabricating a clean-looking (or falsely-drifted) S3 finding out of a bucket the scan literally could not read. This is exactly the failure mode `DriftScanError` exists to prevent (CLAUDE.md: "cannot read the account" and "the account has drifted" are opposite conclusions), just one call deeper than the fetchers already got right. Fixed by only swallowing the documented not-configured codes (`ServerSideEncryptionConfigurationNotFoundError`, `NoSuchPublicAccessBlockConfiguration`) and letting the versioning call — which has no not-configured error at all, only ever a real read failure — raise unguarded; any other `ClientError` now propagates through `_get_actual_state`'s existing catch-all into `DriftScanError`, aborting the scan instead of reporting fiction. Regression test negative-verified (`test_s3_read_denial_fails_the_scan_instead_of_reporting_disabled`). **(3) `_map_terraform_type` mapped 11 Terraform resource types into baselines, but `_get_actual_state` only has fetchers for 4** (EC2 instance, security group, S3 bucket, RDS) — importing a `terraform.tfstate` containing even one `aws_vpc`/`aws_iam_role`/`aws_lambda_function`/etc. created a baseline that would raise `DriftScanError` the instant a scan reached it, and `scan_for_drift`'s loop has no per-baseline error isolation, so that one unsupported baseline permanently aborted scanning of every OTHER (fully supported) resource in the same account. Fixed by narrowing the mapping to only the 4 types with real fetchers — an unsupported Terraform type is now silently skipped at import (same as an already-unrecognized `tf_type`), matching `_get_actual_state`'s own error message ("remove this baseline or add a fetcher for it"). Regression test negative-verified (`test_terraform_import_skips_unsupported_resource_types`). All three fixes verified against the pre-fix code (each new/modified test fails with the exact predicted error before the fix, passes after) and the full suite (745 passed, 1 pre-existing unrelated failure — missing `ANTHROPIC_API_KEY` in the sandbox used to run the suite). **Also fixed, doc-only:** CLAUDE.md's "Concurrency Model" section still claimed production runs "3 plain sync workers" (true as of 2026-07-30) — `devops-agent.service` was changed to `--worker-class gthread --workers 3 --threads 8` as part of the Cloudflare-524 fix, which means requests now genuinely interleave on concurrent threads within one process, making the `threading.local()`-based per-request isolation load-bearing rather than incidental. Updated to reflect the current config and flag that it has already drifted once. **Cataloged, not fixed this pass (lower severity, larger diff):** `capture_baselines_from_account`'s per-bucket S3 read failures during baseline capture are logged but not surfaced to the caller — if every bucket in an account is unreadable, the endpoint still returns `success: true, captured: {s3_bucket: 0}`, indistinguishable from "you have zero buckets" (a softer version of finding (2), since nothing fabricated is returned, just a silent partial failure); the newly-duplicated 5-block FK-cascade delete sequence in `app.py`'s and `api/v1/conversations.py`'s `delete_conversation()` (finding (1)'s fix touched both, but nothing stops the next FK addition from being applied to only one) would be better as one shared `services/conversation_service.py` helper. **Lesson:** a fix for one FK-ordering bug (conversation → its children) doesn't automatically cover the same bug shape one hop further into the graph (message → its own children) — when a delete-cascade fix ships, check whether any of the rows *it* deletes has children of its own that also need to go first, not just whether the top-level object's FK is now satisfied. And "swallow the specific expected error" silently drifting into "swallow every error of that exception class" is the same non-negotiable violation whether it happens in the fetcher CLAUDE.md already flags or three lines deeper inside a helper the fetcher calls. |
| **Scheduled audit found the `/api/chat` keep-alive fix silently broke tool-use tracking/downloads for most users, plus two per-user cloud-context gaps and a drift false-positive (FIXED 2026-08-15)** | Routine code-vulnerability/smell/duplicate scan, scoped to the diff since the 2026-08-08 audit (`85e5132..HEAD`, 113 commits) via three parallel sweeps (auth/isolation/timing/guardrails; SSRF/git-injection/risk-classification; smells/duplicates/fabricated-data). Two sweeps found nothing new (every previously-documented gap remains fixed); the third and a manual follow-up found four real issues, all fixed same day. **(1) HIGH — `app.py`'s `/api/chat` background-thread refactor (see the Cloudflare 524 entry below) reads `DevOpsAgent`'s per-request state from the wrong OS thread.** `_run_agent_call` runs `agent.process_message_isolated(...)` on a brand-new `threading.Thread`; `_generate_chat_response()` then reads `agent.last_tools_used`/`agent.pending_download` after `.join()`ing that thread — but both are `_greenlet_local_property`-backed (`threading.local()`), genuinely thread-local, so the joining thread never sees what the worker thread set and silently got the unset default (`[]`/`None`) instead of an error. Effect: `UsageLog.action_type` was always `'agent_message'` (never `'tool_use'`), the per-extra-tool 0-credit rows and the `first_tool_use` conversion event never fired, and any agent-generated file (keypairs, exported reports) never surfaced a `download_url` — for every `/api/chat` caller, which is the Kimi/free-starter tier's chat path (`templates/index.html`'s `currentModelProvider === 'kimi'` branch, confirmed live in the template) — i.e. most users, with zero exceptions raised. Fixed by capturing `agent.last_tools_used`/`agent.pending_download` inside `_run_agent_call` itself (same thread that set them) into `_agent_result`, and reading from `_agent_result` afterward instead of from `agent` directly. **(2, 3) MEDIUM — two more instances of "a tool execution path outside `process_message_isolated`/`process_message_streaming` didn't set per-user cloud credential context"** (the same bug class as `services/approval_service.py::_execute_tool`, documented in CLAUDE.md's Concurrency Model section): `routes/api_gateway.py`'s `api_execute_tool()` (`/v1/execute`, the developer-API direct-tool-execution endpoint) called the tool handler with **no context set at all**; `routes/mcp.py`'s `_handle_tools_call()` set context via `aws_tools.set_user_context()` directly — AWS-only, so an MCP client calling an Azure/GCP/`devops_operations_tools` tool got no context for that provider. Both fixed by routing through `agent._set_cloud_user_context(user_id)`/`agent._clear_cloud_user_context()` (imported via `from app import agent`), matching the already-correct sibling endpoint `api/v1/tools.py`'s `execute_tool()` (confirmed via `tests/test_api_tools_execute.py`, which already asserts this exact pattern for that endpoint — `/v1/execute` and `/api/v1/tools/execute` are two separate direct-tool-execution endpoints, only one of which had been fixed). **(4) MEDIUM — `services/drift_detection.py`'s `_compare_configs()` compared list-valued properties (`security_groups`, `ingress`) with a plain `!=`.** AWS does not guarantee stable ordering of `SecurityGroups`/`IpPermissions` across `describe_instances`/`describe_security_groups` calls, so a resource that had not changed at all could flag a false "Property 'security_groups' changed" drift purely from reordering — directly undermining the drift feature's credibility, the same class of trust-eroding false-positive the 2026-08-12 drift entries below fixed. Fixed by adding `_lists_equal_unordered()` (sorts both lists on a canonical JSON representation of each element before comparing) and routing list-typed properties through it instead of `!=`. **Verified:** `python3 scripts/check_security_invariants.py` clean; all four edited files pass `py_compile`; full suite **739 passed** (once the sandbox's `ANTHROPIC_API_KEY` env var was set — same pre-existing sandbox-only gap noted in the 2026-08-05 entry below, not a regression); `tests/test_drift_detection.py`+`tests/test_drift_baseline_capture.py` (11 tests, including the reordering case) pass. **Cataloged, not fixed this pass:** `services/chatops_service.py`'s `_cmd_metrics`/`_cmd_oncall` (reachable via `routes/chatops.py`'s Slack/Teams endpoints) return hardcoded fake data under literal `# In a real implementation...` comments — the standing "real cloud account only" rule violation, pre-existing and outside this diff's window; `routes/workflows.py`'s stale-execution reconciliation can misreport a failed workflow as `completed` if *any* assistant reply exists anywhere in its conversation, even an unrelated one; `capture_baselines_from_account()` commits once per resource with no `IntegrityError` handling against the baseline unique constraint (a genuine double-click race throws mid-loop instead of being idempotent). **Lesson:** the thread-local isolation mechanism built specifically to stop *cross-request* state leaks (`_greenlet_local_property`) created the opposite failure here — *within* one logical request split across two OS threads by the keep-alive fix — because it correctly does exactly what it's designed to do (isolate per-thread state) and nothing tells you when your own code crosses a thread boundary it wasn't isolated for. Any code that spawns a background thread to call into `DevOpsAgent` must capture whatever per-request state it needs before that thread exits, not after joining it from elsewhere — and because the failure mode is a silent default, not an exception, it won't show up in error logs; only a broken downstream signal (usage stats, conversion funnel, a missing download) reveals it. |
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

**Follow-up (2026-09-16 scheduled audit):** the hardening above fixed the
*caller-side* check in `rotate_api_key` but left `get_api_key(key_id)` itself —
the method it calls internally — doing a bare `APIKey.query.get(key_id)` with
no ownership filter at all, the exact `ComplianceService.get_policy` anti-pattern
CLAUDE.md warns about for any `self.user_id`-storing service class. Still dead
code (no route calls `APIGatewayService.get_api_key`/`rotate_api_key` directly —
`api/v1/api_keys.py`'s routes use their own correctly-scoped `APIKey.query.filter_by`
calls and a separate `api_key_service.rotate_key`), so not currently exploitable,
but a landmine for whoever wires a route to it next. Fixed by giving
`get_api_key` the same optional `user_id: Optional[int] = None` parameter
(filters by owner when given, matching `revoke_api_key`'s existing convention —
this class's real ownership boundary is the explicit per-call `user_id` param,
not `self.user_id`, since every real call site constructs `APIGatewayService()`
with none) and having `rotate_api_key` pass its `user_id` through to the fetch
instead of re-checking `old_key.user_id` after the fact. Existing
`tests/test_api_key_rotate_ownership.py` still covers the observable behavior.

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

## Scheduled audit: seed_lock premature release + drift-dashboard self-XSS + stale `wf_exec` param (2026-08-18)

A routine scheduled review (four parallel agents, scoped to everything changed
since the 2026-08-11 audit: `git diff 07d87b7...db495f8`, covering drift
detection, pre-built workflows, `app.py`'s chat-keepalive threading rework,
and conversation-delete/model-router/schema-migration) found the drift and
workflow IDOR/SSRF/guardrail surfaces clean, and turned up four real bugs.
One of the four — `api/v1/conversations.py`'s and `app.py`'s
`delete_conversation()` deleting `ChatMessage` rows before `ChatArtifact`
rows, which FKs into `chat_messages.id` with no `ondelete` rule and raises
`ForeignKeyViolation` on Postgres — was independently found and fixed by a
concurrent scheduled session first (merged 2026-08-20, see that entry below);
this session's branch had the same fix queued but rebased onto the
already-merged version rather than duplicating it. The other three were novel
and are fixed here:

1. **`services/ai_infrastructure.py`'s `_get_or_create_system_user()` called
   `db.session.commit()` from inside `seed_public_templates()`'s
   `seed_lock()` block, releasing the Postgres advisory lock early.**
   `seed_lock()` (`services/seed_lock.py`) takes `pg_advisory_xact_lock`,
   which is transaction-scoped and releases on the *next* commit or rollback
   — not on `seed_lock()`'s own commit specifically. `_get_or_create_system_user()`,
   called from inside the lock when a fresh DB has no system user yet, did its
   own intermediate commit to persist the new user, which released the
   advisory lock immediately — before the template rows were even added, let
   alone committed. From that point on, the remaining check-then-insert ran
   completely unprotected, reopening the exact concurrent double-seed race
   (multiple gunicorn workers each inserting the full catalog — the failure
   mode `seed_lock` exists to close, see the 2026-08-12 "Serialize catalog
   seeding" entry) on precisely the case that matters most: first-ever deploy
   against a fresh database, when every worker needs to create the system
   user simultaneously. Fixed by changing `db.session.commit()` to
   `db.session.flush()` — `user.id` is still populated for the caller within
   the same still-open transaction, and `seed_lock()`'s own commit at the end
   persists the user and the templates atomically together. **Any helper
   called from inside a `seed_lock()` block must not commit** — flush if it
   needs an id back, and let the lock's own commit be the only one in the
   block.

2. **`templates/drift/dashboard.html`'s baseline-delete button had a
   self-XSS primitive via `resource_id`.** The button used
   `onclick="deleteBaseline('{{ baseline.resource_type.value }}',
   '{{ baseline.resource_id }}')"` — Jinja's HTML-attribute autoescaping
   encodes a literal `'` to `&#39;`, but the browser HTML-decodes an attribute
   value *before* the JS parser sees it, so `&#39;` becomes a real `'` at
   JS-string-parse time. HTML-escaping does not neutralize a JS-string-context
   breakout inside an inline event handler. `resource_id` is attacker-
   controllable: `import_terraform_state` (`services/drift_detection.py`,
   reachable via `POST /drift/api/import/terraform`) sets it straight from a
   user-uploaded Terraform state JSON's `id`/`arn` field with no validation,
   and the manual `POST /drift/api/baselines` endpoint accepts it directly
   from the request body. A `resource_id` like `x'); alert(document.cookie);
   //` stored as a baseline executes as JS the next time the user's own
   dashboard renders it. Baselines are strictly `user_id`-scoped and both
   creation endpoints require the `approver` role, so impact is self-XSS
   only — but it's a real injection primitive, and the pattern (raw
   interpolation into an inline `onclick=""` string) is one other pages could
   copy. Fixed by switching to `data-resource-type`/`data-resource-id`
   attributes (a plain HTML-attribute context, where Jinja's escaping is
   sufficient) plus a delegated `addEventListener` — no code change needed at
   the call site itself. **Any Jinja value interpolated into an inline
   `onclick="..."` (or other JS-string-context HTML attribute) needs
   `data-*` + `addEventListener`, not `|escape` — HTML escaping alone doesn't
   close this class of injection.**

3. **`templates/index.html`'s workflow-completion tracking (`?wf_exec=<id>`)
   never cleared the URL param, so any later unrelated message in the same
   chat tab silently corrupted a finished workflow execution's status.**
   `markWorkflowExecution(status)` and two duplicated inline PATCH blocks (the
   Kimi-path success handler and the SSE `done` handler) all read `wf_exec`
   fresh from `window.location.search` on every call — unlike the `starter`
   param, which strips itself via `history.replaceState` after firing once.
   Because the param was never removed, sending a second, ordinary chat
   message in that same tab/conversation re-fired `PATCH
   /api/workflows/executions/<wf_exec>` with whatever terminal status that
   *new* turn produced, overwriting the original run's `completed_at`/status
   on `/workflows`' "Recent Executions" list with the unrelated turn's
   outcome. Not cross-user (the PATCH endpoint is still `user_id`-scoped) —
   a data-corruption bug, not a security one. Fixed by having
   `markWorkflowExecution()` strip `wf_exec` from the URL via
   `history.replaceState` once it fires a terminal (`completed`/`failed`)
   status, and replacing the two duplicated inline PATCH blocks (plus the
   initial dispatch PATCH) with calls to the shared helper, closing a
   duplication gap the same audit flagged.

**Findings left open for a follow-up pass, not fixed here** (each is either a
larger architectural call or needs a human decision, matching this repo's
convention of not unilaterally changing behavior a scheduled pass wasn't
asked to own):
- `/api/chat` (unlike its `/api/chat/stream` sibling) has no in-flight/
  duplicate-submission lock per conversation — two concurrent POSTs (two
  tabs/devices, a client retry while a turn is still alive) can each
  independently call `_finalize_turn()` and double-deduct credits. This diff's
  own change (turns now legitimately run up to `CHAT_MAX_TURN_SECONDS`=840s
  with only a spinner visible) makes the window more likely to be hit than
  before.
- `devops-agent.service`'s worker model changed to `--worker-class gthread
  --workers 3 --threads 8` in the same commit that reworked the keepalive —
  real intra-process thread concurrency is now live, which CLAUDE.md's
  "Concurrency Model" section (still describing plain `--workers 3` sync
  workers with no within-process race) doesn't reflect, and which raises the
  odds of the pre-existing unlocked `CreditService.deduct`/
  `UserSubscription.use_credit()` read-modify-write (no `SELECT ... FOR
  UPDATE`, `services/credit_service.py`/`models.py`) actually losing a credit
  decrement under load.
- `Procfile`'s `--timeout 120` vs. the new `CHAT_MAX_TURN_SECONDS` default of
  840s — the Procfile's own comment argues gevent's heartbeat-based timeout
  model (not a hard per-request kill, given gunicorn's gevent worker
  monkey-patches `threading`) makes this safe, and CLAUDE.md already
  documents the Procfile as not matching what's actually deployed (real prod
  runs `devops-agent.service`, not the Procfile) — flagged rather than
  changed since verifying the gevent heartbeat semantics needs runtime
  confirmation, not a code-reading pass.
- `app.py`'s `_finalize_turn()`: the code after `db.session.commit()`
  (download-token lookup, final balance/response-data build) isn't
  exception-guarded, so a failure there reports the whole turn as failed to
  the client even though it already succeeded and was already charged —
  inviting a duplicate paid retry.
- `services/drift_detection.py`: `capture_baselines_from_account` commits
  once per resource (no batching), so a mid-scan failure (e.g. RDS
  permission denied after EC2/security-group succeeded) leaves those earlier
  baselines committed while the route reports the whole capture as failed,
  with no indication to the user that partial state was written. Also,
  `_apply_security_rules`'s `security_drifts = []` is dead — it only mutates
  existing `DriftItem` objects in place and is never appended to, so
  `drift_items.extend(security_drifts)` extends by nothing; pre-existing, not
  touched by the diff that prompted this audit, but the name/return type
  actively suggest it generates new findings, which it doesn't.

## Scheduled audit: GCP generic-API tools bypassed the fail-closed credential contract (FIXED 2026-08-21)

Routine security/code-quality review covering the code merged since the last
scheduled audit (2026-08-11): drift baseline capture, workflow run dispatch,
conversation delete, schema migration, and the chat keepalive rewrite (PR
#141). Those areas checked out clean — no IDOR, SSRF, or fabricated-data
issues found, and the `_run_agent_call`/`_finalize_turn` app-context and
thread-local rules from the keepalive fix are all still respected.

One real gap found in `src/tools/gcp_tools.py`: `gcp_api_read`/`gcp_api_write`
(the generic "call any GCP REST API when no dedicated tool exists" escape
hatch) called `_get_user_gcp_credentials()` directly and passed the result
straight into `googleapiclient.discovery.build(api_name, api_version,
credentials=credentials)` with no check that `credentials` was non-`None`.
Every other client construction in this module goes through
`_get_gcp_credentials_kwargs()`, which raises when the user has no linked GCP
credentials — the fail-closed contract documented in CLAUDE.md's GCP Pattern
section. `_get_user_gcp_credentials()` returns `(None, None)` when the user
has no GCP credentials configured, and `discovery.build()` treats an explicit
`credentials=None` exactly like an omitted argument, falling through to
Application Default Credentials (the app server's own ambient identity) —
the same bug class as the 2026-08-08 GCP credential-isolation fix, missed
here because these two functions predate that fix's audit scope and build a
client via `discovery.build()` rather than a `*Client()` constructor.

**Why the existing structural guard didn't catch it:**
`tests/test_gcp_credential_fail_closed.py`'s
`test_every_gcp_client_construction_passes_credentials` AST check only
matches calls whose callee name ends in `Client` — `discovery.build(...)`
doesn't match. Even if it did, the check is purely syntactic ("a
`credentials=` keyword is present"), not "the value is guaranteed non-None,"
so it wouldn't have caught this shape either way: both functions already
passed `credentials=credentials` syntactically, the bug was that the
variable could be `None`.

**Fix:** both functions now check `if not credentials:` and return the same
fail-closed error dict every other credential-less GCP tool call in this
codebase returns, before `discovery.build()` is ever reached. Two behavioral
regression tests added directly (`test_gcp_api_read_fails_closed_with_no_credentials`,
`test_gcp_api_write_fails_closed_with_no_credentials`) rather than extending
the AST heuristic, since a syntactic check can't distinguish this case —
verified failing against the pre-fix code (`discovery.build()` was reached
and the call proceeded to `.list()`/`.delete()` on the un-credentialed
service).

**Also cleaned up as part of this pass:**
- `src/agent/safety.py`'s `high_risk_tools` set had duplicate entries
  (`execute_script`, `git_delete_branch`, `git_delete_tag`, `delete_eks_cluster`)
  under separately-commented sections — harmless since it's a set literal,
  but copy-paste drift. Deduped; confirmed all 34
  `TestSafetyClassifications` tests still pass and no tool's risk
  classification changed.
- CLAUDE.md's "Concurrency Model" section still asserted production runs
  plain sync workers with "no within-process race," which PR #141
  (2026-08-15) made false: `devops-agent.service` now runs
  `--worker-class gthread --workers 3 --threads 8`, giving each worker
  process real concurrent OS threads against the shared `agent` singleton.
  The existing `threading.local()`-based isolation already protects
  correctly against real threads (not just gevent greenlets), so there was
  no code bug — but the doc's "no race under this config" framing was stale
  and could mislead a future change into treating that isolation as
  optional. Updated to describe the current gthread config and mark the
  isolation as load-bearing today, not defense-in-depth.

## Scheduled audit: two unclassified alerting tools, an unbounded region-scan helper, and a fail-open webhook SSRF check (2026-08-19)

Parallel sweep across the codebase's known risk classes: safety.py risk-classification coverage
(all 742 registered tools), SSRF/login-timing invariant coverage, per-user data isolation (IDOR),
git argument-injection guard coverage, and code duplication. Three real, independently-confirmed
findings, fixed; everything else checked out clean (see below for what was verified with no gaps
found).

1. **`pagerduty_create_incident` / `opsgenie_create_alert` defaulted to low risk** (no confirmation
   prompt) — the same `provider_verb_noun` gap shape documented for `pagerduty_update_incident` /
   `opsgenie_acknowledge_alert` / `opsgenie_close_alert` / `opsgenie_escalate_alert` above, which
   auto-detection's prefix matching doesn't catch. Both tools can page a live on-call engineer or
   team (PagerDuty defaults `urgency` to `'high'`; OpsGenie's `create_alert` takes a `responders`
   list) with zero human-in-the-loop confirmation. Fixed by adding both to `medium_risk_tools` in
   `src/agent/safety.py`, alongside their already-medium siblings.

2. **`aws_tools._parallel_region_scan()` — the shared helper backing 10 all-region scan tools
   (DynamoDB, ElastiCache, API Gateway, Elastic Beanstalk, Lambda, RDS, ECS, EKS, and 2 EC2
   variants) — lost the 25-second `as_completed(..., timeout=25)` bound that the original,
   pre-refactor `list_ec2_all_regions()` still has.** It plain-iterated `for future in futures:
   future.result()` with no timeout, so a single stalled regional API endpoint blocks the entire
   tool call indefinitely — directly collides with this file's documented Cloudflare ~100s
   idle-connection timeout problem (a hang here reads to the user exactly like the 524 incident
   above). Fixed by adding the same `as_completed(futures, timeout=25)` back; every caller already
   wraps the call in `try/except Exception`, so a `TimeoutError` surfaces as a normal
   `{'success': False, 'error': ...}` response, same as any other failure. This is the duplication
   pattern CLAUDE.md warns about generally: a later "cleanup" that consolidated 10 near-identical
   functions into one shared helper silently dropped a safety property one of the originals had.

3. **`app.py`'s `_validate_webhook_url()` (the creation-time check on `POST
   /api/notification-channels`) reimplemented its own weaker, fail-open SSRF check** instead of
   using `assert_safe_external_webhook_url()` — see the SSRF section of CLAUDE.md for the fix
   (delegates to the shared helper now). This is the same "fix landed in one copy, not its
   siblings" pattern the notification_service.py / `test_notification_channel` fixes on
   2026-07-25 were for; this call site was simply missed by that earlier pass.

**Checked and found clean (no changes needed):** all raw `requests.*` call sites (38, all carrying
verified `# ssrf-safe:` exemptions or already routed through `safe_request()`); all `.check_password(`
call sites (all in `routes/auth.py` or `tests/`); all four chat-to-agent entry points still run the
full `sanitize_input → is_guardrail_blocked → validate_message → screen_message` chain; every
`git_tools.py` function passing a caller-supplied ref/branch/pattern positionally to `repo.git.*`
still calls `_reject_flag_like()` (functions without the call were checked individually and are
structurally safe — value embedded in a `--flag=`, or placed after a literal `--` separator); no
new IDOR-class gap in `services/compliance_service.py`, `multi_tenancy.py`, `approval_service.py`,
or any other user/org-scoped service — the getters fixed in the 2026-07-27/08-01 entries above
still filter correctly, and no newly-added getter repeats the pattern.

## Scheduled audit: MCP OAuth authorization-code interception via the built-in client (FIXED 2026-08-30)

Focused audit rotation landed on `routes/mcp.py` OAuth flows (no commits in the prior 26h, so the
day-of-month rotation picked area 0). Found and fixed one critical, live-exploitable bug; no other
issues in the file.

**`oauth_authorize()`'s redirect_uri allowlist was silently skipped for the built-in confidential
client.** The check was:
```python
allowed_redirect_uris = None
if client_id != OAUTH_CLIENT_ID:
    ...
    allowed_redirect_uris = client_record.get('redirect_uris') or None
...
if allowed_redirect_uris and redirect_uri not in allowed_redirect_uris:  # None → never runs
```
For every dynamically-registered client (`POST /mcp/oauth/register`), `redirect_uri` is correctly
checked against the exact URIs that client registered. But `OAUTH_CLIENT_ID` (the built-in
`claude-connector` client used by the "Connect via Claude.ai (Connectors)" self-service flow
documented in `templates/docs.html`) took the `if client_id != OAUTH_CLIENT_ID` false branch,
leaving `allowed_redirect_uris` as `None` — so the membership check was unconditionally skipped for
it. Any `https://` URL (or `http://localhost`) was accepted as this client's redirect target.

This was a complete, working account-takeover chain, not just a theoretical gap, because
`OAUTH_CLIENT_ID` and `OAUTH_CLIENT_SECRET` are both **published in `templates/docs.html`** for
users to paste into claude.ai's "Add custom connector" form — so an attacker doesn't need to guess
either value. And the token endpoint's PKCE branch (`is_public_pkce = bool(code_verifier)`) issues a
token with no `client_secret` at all when a `code_verifier` is present — the "confidential" client
designation provides no actual protection once PKCE is in play. Full exploit:
1. Attacker generates their own PKCE pair and sends a victim a link to
   `/mcp/oauth/authorize?client_id=claude-connector&redirect_uri=https://attacker.example/cb&code_challenge=<attacker's>&...`
   — the domain in the link is the real `devopsagent.io`, so it looks legitimate.
2. Victim logs in for real; the server redirects the authorization `code` to the attacker's
   `redirect_uri` (no allowlist blocked this).
3. Attacker exchanges that code at `/mcp/oauth/token` with their own known `code_verifier` — no
   `client_secret` required (`is_public_pkce` short-circuits `is_known_confidential`).
4. Attacker now holds a valid access token for the victim's account, with full MCP tool access
   (351 AWS tools, Kubernetes, Terraform, etc.) against whatever cloud credentials the victim has
   connected.

No existing test exercised this path — every `redirect_uri` test in `tests/test_mcp_oauth.py` used a
dynamically-registered `client_id`, never `OAUTH_CLIENT_ID` directly.

**Fix:** give the built-in client a real, fixed redirect_uri allowlist
(`_BUILTIN_CLIENT_REDIRECT_URIS` in `routes/mcp.py`, defaulting to the one documented callback
`https://claude.ai/api/mcp/auth_callback`, overridable via `MCP_OAUTH_BUILTIN_REDIRECT_URIS` — comma
separated) and enforce it through the exact same `allowed_redirect_uris` membership check registered
clients already go through, rather than leaving it `None`. Added
`test_builtin_client_id_rejects_attacker_redirect_uri` (proves the fix — asserts 400 for an
attacker-controlled redirect_uri under the built-in client_id) and
`test_builtin_client_id_accepts_documented_redirect_uri` (proves no regression — the documented
claude.ai connector flow still gets a 302 with the auth code) to `tests/test_mcp_oauth.py`.

**Lesson for any future OAuth/DCR-style code in this file:** a "known" or "built-in" client_id is
not inherently more trustworthy than a registered one just because it's a fixed constant — if
anything, a built-in client whose id/secret are published in the app's own docs (for legitimate
self-service reasons) needs its redirect_uri allowlist enforced *more* strictly, since the secret
provides no real boundary once PKCE is available to public clients. Any `if client_id != KNOWN_ID:
... else: <no check>` pattern that special-cases a "trusted" identity out of a validation an
untrusted path already goes through is worth treating as a bug until proven otherwise.

## Scheduled audit: empty-assistant-history fix regressed its own target case, plus a code-smell sweep (2026-08-26)

Two parallel passes: (1) diff review of the ~10 most recent substantive commits against this repo's
known recurring bug classes (SSRF, login-timing, git flag-injection, user isolation, safety.py risk
classification, thread-local context, seeded-catalog races, the gthread concurrency migration); (2)
a duplication/smell sweep across `src/tools/`, `services/`, and `routes/`. One real, confirmed,
reproduced bug found and fixed; one small IDOR-pattern-adjacent duplication fixed; the rest are
flagged, not fixed, per the notes below.

1. **The 2026-08-25 empty-assistant-message fix (see the entry above) broke the exact poisoned
   conversations it was meant to fix.** `core.py`'s two history-reload loops *dropped* an
   empty-content assistant turn instead of replacing it, which collapses the user turn before it
   and the user turn after it into two consecutive `user`-role messages — both Anthropic's and
   Kimi's APIs require strict role alternation, so this trades one guaranteed 400 for a different
   one, for precisely the legacy rows the fix says it "recovers... without a data migration."
   Reproduced directly against `ConversationManager.get_messages_for_api()` (three consecutive
   `'user'` roles from a 3-message poisoned history). The original regression test missed this
   because it only asserted the empty message was *absent*, never that the surrounding roles still
   alternated. **Fixed:** both loops now substitute the same placeholder text used by `app.py`'s
   save path (promoted to a shared `EMPTY_ASSISTANT_PLACEHOLDER` constant in `src/agent/core.py`,
   re-exported via `src/agent/__init__.py`; `app.py`'s two save points now import it instead of
   duplicating the literal string) into the assistant slot rather than omitting the turn. Test
   rewritten to assert the turn is replaced (not dropped) and that the full role sequence
   alternates correctly.

2. **`routes/changes.py`'s change-creation route reimplemented an inline `OrganizationMember.query`
   membership check** instead of calling `_user_active_org_ids()` (the file's own wrapper around
   `services.rbac.user_active_org_ids`, already used elsewhere in the same file) — not itself
   exploitable (the inline check was correct), but the same "reimplemented instead of reusing the
   centralized helper" shape that caused the two documented `user_active_org_ids` recurrences
   elsewhere in the codebase. Fixed by switching to the shared helper; removed the now-unused
   `OrganizationMember` import.

3. **Two redundant inline `import subprocess`/`import os` statements removed from
   `src/tools/docker_tools.py`** (`docker_compose_up`, `docker_compose_down`) — both modules are
   already imported at file scope; harmless but a copy-paste artifact.

**Flagged, not fixed — larger structural items requiring their own reviewed change:**
- The chat-guardrail pipeline (`sanitize_input` → `is_guardrail_blocked` → `validate_message` →
  `screen_message`) is still hand-copied at all 8 call sites across `app.py`, `routes/api_gateway.py`,
  `api/v1/conversations.py`, and `routes/curriculum.py` despite three past incidents of a new entry
  point missing it — no shared `enforce_guardrails()` helper exists yet. See CLAUDE.md's Guardrails
  section for the full call-site list.
- `src/tools/pentest_tools.py` duplicates its scan-runner boilerplate (validator check → build
  command → `subprocess.run` → near-identical exception handling) across 8 functions with no shared
  helper, unlike `terraform_tools.py`'s `_run_terraform_command` / `ansible_tools.py`'s
  `_run_ansible_command`, which already extracted the equivalent pattern.
- `app.py`'s `api_chat` (~617 lines) and `api_chat_stream` (~625 lines) mix guardrails, tier/credit
  checks, keep-alive threading, and tool-loop invocation in one function each; `core.py`'s
  `_call_kimi_api` (~207 lines) and `_call_kimi_api_streaming` (~257 lines) duplicate tool-format
  conversion and usage-logging setup between the sync and streaming paths.
- Scattered unused imports (`app.py`: `flask.flash`, `flask.g`, `login_user`/`logout_user`,
  `hashlib`, several unused `models` symbols; similar in a few `services/*.py` files) — cosmetic,
  not addressed in this pass.

**Checked and found clean:** `scripts/check_security_invariants.py` (SSRF + login-timing AST scan)
reports zero violations; the `/metrics` token comparison (`routes/metrics.py`) already uses
`hmac.compare_digest`, not a plain `==`; no new tools, seeded catalogs, or thread-local context
modules were added in the reviewed window, so patterns 3–8 from the audit checklist had nothing new
to check.

## Scheduled audit: Predictive Scaling fabricated resources/data for every user; fake "applied" success (FIXED 2026-09-02)

No commits landed since the 2026-08-26 audit above (confirmed via `git log --since`), so this pass
did a fresh risk-classification cross-check plus a targeted sweep for the "Non-negotiable: every
feature runs against a real cloud account" rule at the top of CLAUDE.md — the exact rule the
Drift Detection incident (2026-08-12) was written to prevent. Two findings, one fixed, one flagged.

**1. `services/predictive_scaling.py` — the entire Predictive Scaling feature
(`/scaling`, reachable from the chat UI's profile menu, registered blueprint) fabricated its data
for every user, unconditionally, with no `[Sample]`/`[Sandbox]` label anywhere in the template.**
`generate_all_predictions()` called `_ensure_sample_data()`, which seeded three hardcoded fake
resources — `'web-server-1'` / "Web Server ASG", `'prod-database'` / "Production RDS",
`'api-deployment'` / "API Deployment" — with `random.uniform(...)`-generated synthetic CPU/
connection/request time series, byte-identical in shape for every account regardless of whether
they had a cloud account connected. `add_metric()` (the one real-data ingestion point) was never
called from anywhere else in the codebase — nothing fed it live CloudWatch/Prometheus data. On top
of that, `POST /scaling/api/apply/<id>` (gated behind approver permission, and the confirm() dialog
in `scaling/dashboard.html` literally says "This will trigger actual infrastructure changes")
unconditionally set `status: 'applied'` and returned `success: True` with a fabricated
"Successfully initiated scaling for X" message — it never called any AWS/Azure/GCP/Kubernetes API.
An approver who trusted that response would stop looking for other mitigations to a capacity
problem that was never actually fixed. No test file existed for this service at all.

**Fix:** removed `_ensure_sample_data`/`_load_sample_data` entirely (was ~65 lines of synthetic
data generation) rather than gating them, since there is no legitimate always-on fallback per the
non-negotiable rule. Added `register_resource()` as the real extension point a future CloudWatch/
Prometheus ingestion path would call alongside `add_metric()`; `generate_all_predictions()` now
iterates `self.resource_registry[user_id]`, which starts empty and stays empty until something
registers real resources — so the feature now honestly reports "no predictions yet" instead of
inventing data. Fixed the `/api/apply` endpoint to return `success: False` / HTTP 501 with a clear
"not yet implemented, use the equivalent cloud tool in chat" message instead of fabricating
`status: 'applied'`. Updated the dashboard's empty-state copy (previously "All resources are
appropriately sized", which would now be a false claim) to explain that predictions require
historical metrics that aren't being collected yet. Added `tests/test_predictive_scaling.py`
(service-level, no Flask app context needed) asserting: a fresh user gets zero predictions and a
zero summary, `_ensure_sample_data`/`_load_sample_data` no longer exist on the class, and the
registration path still produces correct scale-up predictions once real data is fed in, with
per-user isolation.

**2. Flagged, not fixed — `services/analytics_service.py` has the identical pattern, at larger
scope.** The "Advanced Analytics Dashboard" (`/analytics/`, `/analytics/costs`,
`/analytics/performance`, `/analytics/resources`, all registered routes) is backed end-to-end by
`AnalyticsService._ensure_sample_data()`, which fabricates: a 90-day daily cost series seeded from
`base_cost = 150` plus `random.uniform(-20, 30)` noise; a `_cost_by_service` breakdown with literal
hardcoded dollar figures (`'EC2': 450.00, 'RDS': 280.00, 'S3': 45.00, ...`) and a `_cost_by_team`
breakdown (`'Development': 380.00, 'Production': 420.00, ...`) — both byte-identical for every
user; fabricated incident/deployment/API-call time series; and `get_resource_utilization()` even
generates a fresh `random.uniform(40, 75)` "utilization_avg" on every single call, uncached. Unlike
the scaling fix above, the fabrication here isn't centralized in one seed method — it's threaded
through `get_cost_forecast`, `get_cost_breakdown`, `get_trend_analysis`, `get_dashboard_metrics`,
`get_resource_utilization`, and `get_alerts_summary` individually, and feeds 4 templates plus their
JS chart-rendering code, none of which were read in this pass. This is the same severity as the
finding above (cost *forecasting* built on fake numbers is arguably more consequential — it's the
kind of output someone would act on for a real budget decision) but a safe fix needs to read all 4
consumer templates/JS first to confirm nothing crashes on genuinely empty data, which didn't fit in
this pass — treat as the top-priority item for the next audit or a dedicated PR.

## Agent felt slow and kept saying it lacked the right tool (2026-09-02)

**Symptom (user report):** from the chat UI the agent "is taking a lot of time or
complaining about not having access to the right tool to call."

**Not one bug — four, all in progressive tool loading (`src/agent/tool_selection.py`)
and its Kimi wiring.** Diagnosed by reading the code plus a simulation of the selector
against the real 744-tool catalog; production logs were not available for this pass.

1. **`search_tools` could not actually recover anything on the Kimi path.**
   `_call_kimi_api` and `_call_kimi_api_streaming` each built `oai_tools` **once,
   before** their tool loop. The `search_tools` handler appends matches to
   `_tools_override` mid-loop and replies "these tools are now available — call them
   directly", but every subsequent request in that turn still carried the pre-loop
   list. The model was told a tool existed and then handed a request without it, so
   it either burned an iteration or said it had no such tool. Free and starter tiers
   both run this path, so this was the common case; the Claude paths re-read the
   override each iteration and were unaffected. Fixed with `_current_oai_tools()`,
   called inside both loops.

2. **The `max_tools` cap silently dropped a category the user had named.**
   "show me the pods in my eks cluster" matches `kubernetes` (76 tools) and
   `aws.eks` (28); base + both exceeded the cap, so the greedy pass kept EKS and
   dropped all 76 Kubernetes tools — the user asked about pods and got no pod tools.
   Fixed by exempting every category tied for the top explicit keyword score from the
   cap. Weaker signals stay greedy.

3. **Provider-generic nouns were pinned to one provider, and the escape hatches were
   filtered out.** "check my database" selected RDS only; "list my running containers"
   selected only local Docker tools (which run on the app server, not the user's
   cloud), hiding ECS/EKS/Kubernetes/Azure/GCP. Meanwhile `azure_api_read`,
   `gcp_api_read`, `k8s_api_read` and their siblings were themselves filtered out
   unless the provider was named — while the system prompt tells the model to use
   exactly those and to "NEVER say 'I don't have a tool'". Fixed with `GENERIC_NOUNS`
   (nouns map to an ordered cross-provider category list, narrowed to the user's
   actually-connected clouds via `credential_service.get_user_configured_providers`)
   and `ALWAYS_TOOL_NAMES` (the eight hatches + `search_tools`, included by name).

4. **Selection read only the current message, which is what made it slow.**
   Follow-ups carrying no keywords ("yes go ahead", "now delete it") matched nothing,
   so the selector returned `None` and the caller shipped all ~745 schemas — on Kimi
   that also bypasses the cap entirely, since the cap only applies once a subset is
   chosen. Every one of up to 20 reasoning-model iterations then paid for the full
   catalog. Fixed by feeding the last 6 user turns in (`history_messages`), plus an
   AWS-region-token signal so "list all resources in us-east-1" stops falling through.

**Measured on the real catalog (cap 100), before → after:**

| Query | Before | After |
|---|---|---|
| show me the pods in my eks cluster | 50 (no K8s tools) | 130 (both kept) |
| list my running containers | 35 (Docker only) | 85 (ECS/EKS/K8s) |
| yes go ahead (after an EC2 turn) | 744 (full catalog) | 57 |
| list all resources in us-east-1 | 744 (full catalog) | ~60 |
| what is my aws bill this month | 91 | 86 |

**Gotcha worth remembering:** the AWS seed (a bare "aws" with no service named seeds
ec2/s3/iam/vpc) initially went into the cap-exempt tied-top tier along with real
keyword matches. Because all four seeds tie at score 1, "what is my aws bill this
month" shipped 197 tools against a cap of 100. A *guessed* category must never claim
the cap-exempt slot — only categories the user actually named.

**Tests:** `tests/test_tool_selection.py` (10 new cases) and
`tests/test_kimi_tool_refresh.py` (verified failing against pre-fix `core.py`, passing
after). Full suite unchanged: identical 15 failures / 254 errors before and after,
+11 passes. (Those pre-existing failures are a local Python 3.9 artifact — the project
needs 3.10+ for `X | None` syntax — not a real regression.)

## Agent ran `list_iam_roles` when asked to create an Ubuntu EC2 instance (2026-09-02)

**Symptom (live user report, with production confirmation):** "create an ec2 instance
using ubuntu on a t2.micro" produced no instance. The agent replied that its calls were
"misrouted to an IAM role listing". `usage_logs` confirms exactly one tool ran that turn:

```
2026-09-02 16:00:49 | tool_use | list_iam_roles | kimi-k3 | True
```

The identical request on 2026-09-01 ran `gcp_api_read` + `gcp_api_write` and ended in
"Maximum number of tool executions reached." Different wrong tool each time.

**This was NOT the progressive-tool-loading bug fixed earlier the same day (#162).**
That fix worked: selection correctly offered the EC2 category and correctly withheld
every IAM tool. Three separate defects combined.

**1. Root cause — the request was unsatisfiable, so the model guessed.**
`create_ec2_instance` requires a concrete `ami_id`, and **nothing in the 745-tool
catalog could look one up**. The only AMI tools were `create_ami` (images a running
instance) and `deregister_ami`. There was no `describe_images` wrapper, no distro
resolver. The model's only real option was `aws_api_read('ec2','describe_images', …)`
with the right owner/filter incantation, which it never found. Fixed by adding
`find_ami` (`src/tools/aws_tools.py`), which resolves distro + version + architecture
to the newest matching AMI. **It pins the vendor's own AWS owner account** — matching
an AMI by name alone is unsafe, since anyone can publish a public image with a
lookalike name.

**2. Tool filtering was advisory, not enforced.** All five execution sites tested
`tool_name in self.tools` — the *full* registry — never the filtered set actually sent
to the model. So a guessed name that happened to exist ran for real against the user's
account. This is why a withheld `list_iam_roles` still listed 8 real IAM roles. Fixed
with `core._is_tool_offered()` / `_not_offered_result()`; a withheld tool now returns an
error naming `search_tools` as the way back. **The lesson: filtering the tool list is a
prompt-level hint, not a control. If a tool must not run, the executor has to say so.**

**3. `search_tools` — the one recovery path — ranked by raw substring match.**
`sum(1 for t in terms if t in haystack)` meant short terms matched inside unrelated
words: "ami" matches "dyn**ami**c", so the query "ubuntu ami" returned
`list_eks_clusters` as the top hit, ahead of `create_ami`. Even a model that did the
right thing got junk. Now whole-word matched with the tool name weighted 10x over the
description; "ubuntu ami" returns `find_ami`, `create_ami`, `deregister_ami`.

**Note on fix ordering:** #162 made `search_tools` actually work on the Kimi path (its
results previously never reached the model). That made defect 3 newly *reachable* —
worth remembering that repairing a recovery path can expose the quality of what it
recovers.

**Guard:** `tests/test_ami_lookup_and_tool_enforcement.py` (17 cases). Adding `find_ami`
also tripped `tests/test_tool_counts.py`, which pins the documented tool totals to the
registry — 745→746 across 7 templates + CLAUDE.md, AWS 351→352, MCP subset 702→703.
That test is doing its job; update the user-facing numbers, never the test.

## Same incident, second follow-up: runtime self-correction (2026-09-02)

After the description cross-references above (#164) deployed and passed its own
health check, the identical request failed a fourth time on the same conversation.
A description is advisory — nothing stops a model from not reading it, or from
reading it and guessing wrong anyway under a long, noisy conversation history (this
thread had ~20 prior turns spanning IAM, GCP, RDS, Nexus, and Lambda tangents).

**Structural fix, not another description tweak: make the two tools self-correct
in their own result, at the exact moment the mistake happens.**

- `create_ec2_instance`'s `ami_id`/`instance_type` were required positional
  params with no default. A call missing either raised a bare `TypeError` before
  the function body ever ran, caught generically several layers up and turned
  into an opaque "missing 1 required positional argument" string with no path
  back to `find_ami`. Made both `Optional` in the signature (the tool **schema**
  still lists both in `required` — the runtime guard is defense-in-depth, not
  permission to omit them) and added an explicit early check that returns a
  guided error naming `find_ami` and warning against `manage_ec2_instance`.
- `manage_ec2_instance`'s `ClientError` handler now special-cases the
  `InvalidInstanceID.*` family — exactly what AWS returns when the model calls
  `action='start'` with a fabricated `instance_id`, which is what actually
  happened in production — and enriches the message with the same redirect.
  Every other AWS error code passes through unchanged; misdiagnosing an
  unrelated failure (e.g. a permissions error) as "go create one instead" would
  be worse than the plain error.

**Why this matters more than the description fix:** the enriched error lands in
the tool-result message the model reads on its very next iteration, inside the
*same* turn and the *same* tool-call budget — no new user message, no re-reading
a schema, no dependence on the model's own judgment about which tool to try.
Verified locally that `find_ami`/`create_ec2_instance`/`manage_ec2_instance` are
all still correctly offered under this exact conversation's real noisy history
(20 prior turns) before shipping.

**A separate, non-code factor:** this specific conversation had accumulated the
model's own prior wrong "misrouting" narrative across several turns. Once that
framing is in the replayed history, the model tends to repeat it rather than try
fresh. A poisoned conversation history is not something a tool-level fix can
clean up — starting a new conversation is the only way to get an unbiased retry
of a request that failed repeatedly in an old thread.

**Tests:** 6 more cases in `tests/test_ami_lookup_and_tool_enforcement.py`
(now 27 total for this incident) — the missing-arg guard never reaches boto3,
the schema's `required` list is unchanged, `InvalidInstanceID.*` gets the
redirect, and an unrelated error code does not.

## Root cause found: escape hatches were always-offered across ALL providers (2026-09-02)

After three merged fixes for the "create an ec2 instance using ubuntu" incident
(#162 progressive loading, #163 find_ami + enforcement, #164 description
cross-refs, #165 runtime self-correction), the identical request kept failing —
now guessing CloudFormation, then Kubernetes, then RDS, each narrated to the
user as "misrouted" with a fabricated-sounding AWS error message. usage_logs
confirmed `k8s_api_read` **actually executed** (no exception, so `success=True`)
for a plain "create an ec2 instance" request that named nothing Kubernetes-
related anywhere in the message or its history.

**Root cause: `#163`'s `ALWAYS_TOOL_NAMES` made all eight provider-generic
escape hatches (`aws_api_read`/`write`, `azure_*`, `gcp_*`, `k8s_*`)
unconditionally present on every single turn, regardless of the message.**
That fix was correct in spirit — the system prompt tells the model to fall
back on these and never say it lacks a tool, so filtering them out entirely
(the original bug) was wrong. But making them *all* always-present introduced
a new failure mode: a plain AWS EC2 request now always carried Kubernetes,
GCP, and Azure escape hatches too. A model struggling to find the right
AWS-specific tool had four cross-cloud generic hatches sitting right there to
grab instead — and it did, repeatedly, across at least four different wrong
guesses in one afternoon (RDS, Nexus, IAM, GCP, Lambda-shaped, CloudFormation,
Kubernetes, EC2 keypair) on the same conversation.

**Fix:** `HATCH_PAIRS_BY_PROVIDER` + `_hatch_providers_for()` scope each
provider's pair to whether *this turn's* matched categories (current message,
generic nouns, and history — the same three signals selection already
computes) actually implicate that provider. `search_tools` stays the one
truly unconditional hatch. Verified against this exact conversation's real
noisy 20-turn history before shipping: `find_ami`/`create_ec2_instance`/
`manage_ec2_instance`/`aws_api_read`/`aws_api_write` are offered;
`gcp_api_read`/`gcp_api_write`/`k8s_api_read`/`k8s_api_write`/`azure_api_read`/
`azure_api_write` are not.

**Two urgent side effects surfaced by this investigation, unrelated to tool
selection and requiring account-owner action, not a code fix:**
- `create_rds_instance` executed successfully (`usage_logs`, 2026-09-02
  13:50:02, before any of these fixes were deployed) — check the AWS console
  for an RDS instance that shouldn't exist.
- The assistant reported creating an EC2 key pair `ubuntu_key` with a
  plausible key-pair ID at 17:00:43, but **no corresponding `tool_use` row
  exists in `usage_logs` for that turn** (it logged as `agent_message`,
  `tool_name=None`) — meaning either `create_ec2_keypair` genuinely ran and
  the per-turn tool-name logging silently dropped it (a real gap, not yet
  root-caused — candidate for the next audit given the documented
  `last_tools_used` greenlet-local read-ordering fragility in the Cloudflare
  keep-alive section above), or the model fabricated the entire result
  including a fake-but-realistic key-pair ID. Either way: if a real
  `ubuntu_key` pair exists in `us-east-1`, its private key material passed
  through this chat's stored history and the Kimi API request — treat it as
  compromised, delete it, and do not reuse the key file.
- Also observed: this account's free-tier credits were exhausted from
  repeated retries of the same failing request (at least ten user turns in
  one afternoon, each consuming a credit regardless of outcome) — expected
  behavior given free tier is a one-time, non-renewing 20-credit grant, not a
  bug, but worth knowing before assuming a credits-display bug.

**Structural lesson:** an "always available" tool set is not free of
selection risk just because it's small (eight tools, not 745) — it still
needs to be scoped to relevance, or it becomes exactly the kind of
easy-to-grab wrong answer that a struggling model reaches for. The fix for
"a needed tool was filtered out" is not "never filter this tool," it's
"filter it correctly."

**Tests:** `tests/test_tool_selection.py` — `test_escape_hatches_scoped_to_implicated_providers`
(replaces the old `test_escape_hatches_always_present`, which encoded the
bug), `test_escape_hatches_scoped_to_each_provider_named`,
`test_kubernetes_request_gets_only_the_k8s_hatch`.

## "It says I have 0 credits" when the real balance was 15 (2026-09-02)

**Live report:** "still complaining about credits, when i have 15 credits."
Queried the account directly (the credits snapshot section above, once moved
early enough to survive the SSM output cap): `remaining=15` — the DB and the
user agreed. So the credit *gate* (`subscription.has_credits()`, checked
identically on both `/api/chat` and `/api/chat/stream`) was never the problem;
it correctly evaluates true at 15 and lets the turn through.

**Root cause:** `/api/chat/stream`'s generic `except Exception as e:` handler
— the catch-all for any unrelated failure mid-turn (a provider timeout, a
tool crash, a malformed JSON response) — hardcoded
`{'type': 'done', 'credits_remaining': 0, 'error': True}` regardless of the
user's actual balance. The SSE `done` handler in `templates/index.html` calls
`updateCreditsDisplay(evt.credits_remaining)` unconditionally whenever the
field is present, so the header badge got overwritten to 0 on **any**
transient error, with no relationship to the real number.

**Fix (`app.py`):** the handler now looks up `CreditService.balance(uid)`
inside the `app.app_context()` block it already enters to roll back the
session, and reports the real number — or omits `credits_remaining` entirely
if that lookup itself fails, since the frontend already treats "field absent"
as "leave the display alone."

**Frontend hardening, defense-in-depth (`templates/index.html`):** the
*non-streaming* `/api/chat` response handler had the more dangerous sibling
of this same pattern — it triggered a **full input lockout** (disabled
message box, disabled send button, "Trial ended" placeholder, upgrade
banner) on a bare `data.credits_remaining === 0` check, with no relation to
`data.trial_ended`. Nothing in the current codebase was found to send a
false 0 through that specific path, but the check itself was one bug away
from turning "an unrelated error happened" into "your account looks
permanently locked until you reload the page." Changed to gate on
`data.trial_ended` explicitly, matching the (already-safe) SSE `done` handler
a few hundred lines below it, which never checked the raw number in the
first place.

**Lesson:** a UI element wired to "the balance is exactly 0" is implicitly
trusting every code path that can produce that number to mean the same
thing. A generic error handler and a real credit-exhaustion check are not
the same event, and hardcoding a sentinel value that happens to coincide
with a real value's meaning (0 credits = 0 the number) is the same shape of
bug as the escape-hatch and tool-enforcement fixes above: treat generic
fallback behavior as low-risk just because it's simple, and it becomes
exactly the path that misfires.

**Tests:** `tests/test_streaming_credits_display.py` — verified failing
against the pre-fix `app.py` (both backend cases), passing after. Follows
this codebase's existing pattern (`tests/test_sandbox_activation.py`) of a
source-level check for logic embedded in app.py's route closures, which
aren't practical to exercise via a full SSE test client.

## Correction: the "unwanted RDS instance" flag from the escape-hatch fix above was wrong (2026-09-02)

The prior entry recommended checking AWS for an RDS instance based on
`usage_logs` showing `create_rds_instance` with `success=True`. The user
checked: no RDS instance exists. That flag was a misreading of what the
`success` column actually records.

**`success` on a `UsageLog` row (`app.py`, both the non-streaming and
streaming write sites) reflects whether the chat *turn* completed without
the agent/provider call itself raising — not whether any individual tool
call inside that turn returned `{'success': True}`.** A tool like
`create_rds_instance` catches its own `ClientError` and returns
`{'success': False, 'error': ...}` on a real AWS rejection (missing subnet
group, invalid engine version, bad parameter, whatever). The Kimi turn still
finishes normally with that failure folded into the assistant's response, so
the row logs `success=True` regardless of what AWS actually did.

**This means `usage_logs.tool_name`/`success` alone cannot answer "did this
tool call actually succeed against the cloud account" — only "did the turn
that contained it complete."** The only way to know the individual tool
result is `chat_messages.tool_trace`, and that's written by the streaming
route only (see the Cloudflare keep-alive section above) — so for the
non-streaming Kimi tier used throughout this whole incident, there was no
DB-queryable signal for individual tool-call success at all. The
`check-errors.yml` "TOOL CALL FAILURES" section already has this exact
caveat in a comment for the same reason.

**Practical effect on this investigation:** the `create_ec2_keypair` claim at
17:00:43 (no matching `tool_use` row at all, unlike RDS which had one marked
falsely-successful) is a *different* shape of gap and still needs the user's
own AWS-console check — a missing row means either the call never happened
(model fabricated the whole response) or `_last_tools_used` silently
dropped it, not "it succeeded." Don't conflate the two: a *present* `tool_use`
row with `success=True` is not proof the tool's own result was
`{'success': True}`; an *absent* row is not proof nothing ran.

**Follow-up worth doing, not done here:** `UsageLog` could carry the tool's
own `result.get('success')` per tool (not just the turn-level Kimi/Claude
completion flag) — cheap to add at the same write site, and it would have
answered "was an RDS instance actually created" from the DB in one query
instead of requiring an AWS console check. **Done 2026-09-05 — see the
tool-call observability entry below.**

## Tool-call observability: consistent per-call recording + a DB signal for misrouting (2026-09-05)

Follow-up to the whole 2026-09-02 "misrouting" series above. Nothing was
broken in production — this closes the *visibility* gaps those investigations
kept running into.

**Three defects, all about not being able to see a tool call after the fact:**

1. **`_not_offered_result()` fired silently.** A model emitting a tool name
   progressive selection never sent is *the* signal that selection is too
   tight or a request class has no satisfiable tool — the exact 2026-09-02
   failure mode — and it produced no log line, no metric, nothing. Now emits a
   structured `tool-not-offered` warning (grep for it) naming the tool, whether
   it was withheld vs. genuinely unknown, and the offered-tool count.

2. **`_last_tools_used` was appended inconsistently at the 5 executor sites.**
   The Kimi paths appended only after a handler returned; the Claude path
   appended unconditionally (sandbox and not-offered included). So a guessed
   not-offered tool on the **Kimi non-streaming tier** left no trace in
   `_last_tools_used` → no `usage_logs` row at all — this is what made the
   `create_ec2_keypair` claim at 17:00:43 (entry above) impossible to
   adjudicate from the DB. All 5 sites now route through
   `core._record_tool_call(tool_name, result, outcome=...)` where `outcome` is
   `ran` / `raised` / `not_offered`. `_last_tools_used` (and its dedup
   `last_tools_used` property, which drives primary-tool attribution in app.py)
   still counts only `ran` calls — unchanged semantics — while the new
   `_tool_call_log` / `last_tool_calls` property records **every** call with
   its real per-tool outcome. `process_message_streaming` also never reset
   `_last_tools_used` (a pooled worker thread carried the prior turn's list);
   both trackers are now reset in all three entry points.

3. **`usage_logs.success` on a per-tool row was the turn-completion flag**
   (the false "unwanted RDS instance" alarm, entry above). `app.py`'s two
   write sites (`_finalize_turn`, the streaming finalizer) now share
   `_record_tool_usage()`, which writes each per-tool row's real
   `success` / `error_message` from `agent.last_tool_calls`, corrects the
   primary/turn row when its own tool failed, and writes a
   `action_type='tool_not_offered'` row for each guessed tool. `routes/analytics.py`'s
   `api_tool_usage` (per-tool `success_rate`, grouped by `tool_name`) was
   already reading `usage_logs.success` — it now returns real numbers.

**Monitoring:** `check-errors.yml` gained a "TOOL MISROUTING" section —
counts `tool_not_offered` rows and real per-tool `tool_use` failures over 7
days, both from `usage_logs` (works on the Kimi non-streaming tier, which
writes no `tool_trace`). A nonzero not-offered count is the alarm that a
2026-09-02-style regression is happening again.

**Not touched:** `routes/api_gateway.py`'s `/v1/agent` developer API has its
own `api_tool_use` write site with the same turn-vs-tool `success` conflation
— out of scope for this pass (chat paths only), worth a follow-up.

**Tests:** `tests/test_tool_call_observability.py` (11 cases: the warning,
`_record_tool_call` outcomes, end-to-end Kimi non-streaming for a guessed /
failed / raising tool) + `tests/test_chat_keepalive.py::test_per_tool_success_and_not_offered_rows_reach_the_usage_log`.
Full suite green.

## Execution Integrity Phase 1 — prompt rules + session resource registry (2026-09-05)

The user supplied a 9-rule "Execution Integrity & Resilience" spec after the
2026-09-02 misrouting series, to harden against the whole class (fabricated
results, eventual-consistency mishandling, dishonest error narration,
dead-ending, credit waste, state disputes). Full spec + deferred-phase
decisions: `docs/execution-integrity.md`.

**Phase 1 (this change) is prompt + cheap guardrails only:**

- **`=== EXECUTION INTEGRITY ===`** block added to `STABLE_SYSTEM_PROMPT`
  (`src/agent/core.py`) — verified-results-only, eventual-consistency ("never
  call a <5-min-old resource 'not found'", with the exact "I cannot confirm
  it via a read yet" phrasing), the (a)/(b)/(c) error classification, the
  retry→generic-API→IaC fallback order, and "console truth beats agent
  inference". Prompt-cache structural invariants unchanged
  (`test_prompt_cache.py` green).
- **Session resource registry (rule 9):** `_is_creating_tool` +
  `_extract_created_resource_ids` feed `agent._created_resources` per turn;
  `_audit_chat_deletion` renamed to **`_audit_infrastructure_change`** and
  extended with an `action_type='create'` branch that stamps
  `change_details['conversation_id']`. `_session_resource_context()` reads
  those rows back (same conversation, last 30 min) into the volatile prompt
  tail via `build_volatile_tail(preferences, trial, session_context=)` (new
  3rd param — 1/2-arg calls byte-identical). Chosen over an
  `InfrastructureChange.conversation_id` migration: the id lives in the
  existing `change_details` JSON and is filtered Python-side (low row count).
- **Guard-note surfacing (rule 8):** `_repeat_guard_result` and a ≥3×
  not-offered guess arm `_note_guard`; `_guard_notes_suffix()` appends a
  plain-language "Tool-selection note" to the user-facing response (never
  replaces it). Wired into the non-streaming return, the Kimi-streaming
  yield-from, and the Claude-streaming `end_turn` exit. `_GuardHost` test
  stub in `test_tool_selection_engaged.py` gained `_note_guard` /
  `_turn_guard_notes`.
- Also fixed a pre-existing asymmetry: `process_message` (legacy Claude-only)
  never reset `_repeat_guard`; now resets all per-turn trackers like the
  other two entry points.

**Dispatch cannot misroute** — it is a dict lookup; rule 8's "alert on
`tool_requested` != `tool_executed`" targets a layer that does not fail. The
real signal (model guessing a wrong/withheld name) is already covered by
`_repeat_guard` (#171) + `tool-not-offered` log/DB (#173); Phase 1 only adds
the user-facing surface.

**Deferred (decisions in `docs/execution-integrity.md`):** synchronous
read-back verification engine (`services/mutation_verifier.py`, ~15s backoff
cap, not 60s); credit pre-warn + 60s read cache; CloudFormation/Terraform
fallback generation + retry queue. Rule 6 (tier-gated instance types)
dropped — no such feature exists.

**Tests:** `tests/test_execution_integrity.py` (18 cases). Full suite green.

## Execution Integrity Phase 2 — post-create read-back verification (2026-09-06)

Rule 2's runtime, deferred out of Phase 1. `services/mutation_verifier.py` +
`DevOpsAgent._verify_and_annotate`, wired into all 5 tool-execution sites in
`core.py` right after `_record_tool_call(..., outcome='ran')`.

**Flow:** a creating tool returns `success: True` → its dedicated read tool
(same per-user cloud client) is polled `DEFAULT_BACKOFF = (0, 1, 2, 5, 7)s`
(first attempt immediate, ~15s total — deliberately not the spec's 60s) →
the tool result the model reads next iteration gains a `_verification` key:
`{status: 'confirmed', resource_id, via, after_seconds}` or
`{status: 'unconfirmed', resource_id, via, message}` where `message` is the
verbatim "Create returned ID <X>, but I cannot confirm it via a read yet…".
The `STABLE_SYSTEM_PROMPT` AUTOMATIC VERIFICATION line tells the model
`unconfirmed` is not a failure. The `_created_resources` registry entry is
tagged `verified: true|false`.

**Confirmation predicate:** `read_result.get('success') is True` AND the
resource id appears verbatim in the read payload — every read tool in the
Phase 2 set echoes the queried id on success, so the echo check also guards
against a success with an empty/unrelated body.

**Verifiable set (Phase 2):** `create_ec2_instance`/`run_instances` →
`get_ec2_instances`; `create_security_group` → `describe_security_group`;
`create_vpc` → `describe_vpc`; `create_rds_instance` → `describe_rds_instance`;
`create_s3_bucket` → `get_s3_bucket_info`.

**Guards:** skipped in sandbox; kill-switch `mutation_verify.enabled`
(default true); `MAX_VERIFICATIONS_PER_TURN = 3` (a turn launching 10
instances must not add 150s — the rest are registered unverified); every
exception path leaves the result untouched (`verify_mutation` never raises —
a read that errors just counts as "not confirmed yet").

**Not covered:** deletes (verify the resource is *gone* — a different,
state-transition-aware predicate) and updates. Phase 2b.

**`verify_mutation` is injectable** (`call_tool`, `sleep`) so it unit-tests
without a cloud account. Default `sleep` is resolved lazily inside the loop
(`sleep or time.sleep`), not bound as a default arg — so `patch('time.sleep')`
in tests actually takes effect.

**Tests:** `tests/test_mutation_verifier.py` (14 cases). Full suite green.

## Execution Integrity Phase 2b — delete verification (2026-09-06)

Extends Phase 2's `services/mutation_verifier.py` to deleting tools. Same
`verify_mutation` entry point (now dispatches create vs. delete), same
`_verify_and_annotate` wiring — a delete result is `{'success': True}` and
flows through the 5 execution sites identically.

**Per-attempt the read-back resolves to `gone` / `present` / `unknown`:**
- `gone` → `_verification.status='confirmed'` (`action='delete'`). Triggers:
  a describe-by-id read that 404s with a code in `_NOT_FOUND_CODES`; an EC2
  instance in `shutting-down`/`terminated` or absent from the filtered list;
  an S3 bucket absent from `list_s3_buckets`.
- `present` → after all attempts, `unconfirmed` — "a read still shows it, may
  still be shutting down".
- `unknown` → a read that failed for a **non-NotFound** reason (AccessDenied,
  Throttling). **Never** treated as `gone` — that is the "cannot read the
  account vs. a finding" trap CLAUDE.md's drift rule exists to prevent. After
  all attempts, `unconfirmed` — "could not verify removal, the read-back is
  failing".

**Delete-verifiable set:** `delete_ec2_instance` /
`manage_ec2_instance(action='terminate')` → `get_ec2_instances`;
`delete_security_group` → `describe_security_group`; `delete_vpc` →
`describe_vpc`; `delete_rds_instance` → `describe_rds_instance`;
`delete_s3_bucket` → `list_s3_buckets` (NOT `get_s3_bucket_info` — it swallows
`NoSuchBucket` in a nested `except` and returns `success: True` for a missing
bucket, so it can't confirm a deletion).

**`will_verify(tool_name, tool_input)`** added alongside `is_verifiable` —
also honours a `_DeleteSpec.applies` predicate, so `manage_ec2_instance` with
a non-`terminate` action spends no per-turn verification slot. The
`_created_resources` registry is tagged only for `action == 'create'` (a
create-then-delete in one turn must not flip a deleted resource to
`verified: true`).

**Not covered:** update verification (Phase 2c, not started).

**Tests:** `tests/test_mutation_verifier.py` (now 25 cases, +11 for deletes).
Full suite green.

## Execution Integrity Phase 2c — update verification (2026-09-06)

Extends the read-back verifier to updating tools. `verify_mutation` was
refactored from a create/delete `if`-ladder into `_pick_spec` (dispatch,
honours each spec's `applies`) + a shared `_poll` loop + three per-action
tails.

**Per attempt the read-back resolves to `applied` / `not_yet` / `unknown`**
(`_update_state`): build `{read_field: target}` from the params the caller
actually passed (`_UpdateSpec.expected`), locate the resource in the read
(`_UpdateSpec.find` for list-style reads), compare.
- `applied` → `status='confirmed'` + a `fields` list. An `accepted_states`
  hit (RDS `status == 'modifying'`) also counts — the change was accepted.
- `not_yet` → after all attempts, `unconfirmed` — "a read does not yet show
  the new value for <fields>".
- `unknown` → the read failed, OR nothing checkable was passed (e.g.
  `modify_rds_instance` with only `backup_retention_period`, which no read
  tool surfaces). After all attempts, `unconfirmed` — "could not verify".

**Update-verifiable set:** `resize_ec2_instance` → `get_ec2_instances`
(`instance_type`); `manage_ec2_instance(start|stop|reboot)` →
`get_ec2_instances` (`state`); `update_ecs_service` → `list_ecs_services`
(`desired_count`); `update_lambda_function_config` → `list_lambda_functions`
(`memory_size`/`timeout`/`runtime`); `modify_rds_instance` →
`describe_rds_instance` (`db_instance_class`/`engine_version`).

**`manage_ec2_instance` is now in all three spec maps** — `terminate` →
delete, `start`/`stop`/`reboot` → update, anything else → not verified.
`will_verify` now just calls `_pick_spec` and checks the action is non-None.

**Not covered:** SG-rule changes (`authorize_*`/`revoke_*` — expected is a
rule shape, not a scalar), tag ops, `update_cloudformation_stack`.

**Tests:** `tests/test_mutation_verifier.py` — now 35 cases (+10 for updates,
incl. read-failure-is-not-applied and nothing-checkable cases). Full suite
green.

## Execution Integrity Phase 3 — credit protection (2026-09-06)

Rule 5. Two lightweight pieces; the per-turn credit model is unchanged.

**Low-credit warning:** `app._low_credit_warning(credits_remaining)` →
`{'credits_remaining', 'message'}` when the post-turn balance is
`1..LOW_CREDIT_THRESHOLD` (5). Attached as `low_credit_warning` to the
`/api/chat` JSON body and the `/api/chat/stream` `done` SSE event.
`templates/index.html`'s `maybeWarnLowCredit()` toasts it, deduped on the
balance value (a user sitting at 3 isn't toasted every message). The existing
one-time email at exactly 5 is untouched. `0`-and-below keeps the exhausted
upgrade-pitch path.

**60s read cache — `services/tool_cache.py`:** `READ_CACHE` (`_ReadCache`,
process-wide, `threading.Lock`) caches **successful read** results by
`(user_id, tool_name, canonical_args)` for `TTL_SECONDS = 60`, bounded 512.
`is_read_tool()` = `get_`/`list_`/`describe_` prefix, `_api_read` substring,
or `find_ami`/`search_tools`, minus a deny-list
(`get_secret_value`/`generate_s3_presigned_url`/`get_ec2_console_output`/…).
`DevOpsAgent._invoke_tool()` replaces the bare `self.tools[name](**input)` at
all 5 execution sites — cache-lookup for reads, store on success, and
**`READ_CACHE.invalidate_user(uid)` after any mutating call** (a stale read
that contradicts a just-applied change is exactly what the Phase 2 verifier
guards against — coarse invalidation is fine, mutations are rare).
`canonical_args` = `_repeat_key`. Kill-switch `tool_cache.enabled`. The Phase 2
verifier's own read-backs call `self.tools.get()` directly (un-cached, always
fresh).

**Not done:** rule 5's literal "warn *before* the operation" — a chat turn's
message is already sent by the time the server sees the balance; the
every-turn warning informs the *next* message instead.

**Tests:** `tests/test_tool_cache.py` (31 cases). Phase-3 + adjacent suites
green (327). Full local suite has the pre-existing load-dependent SQLite
flakiness (see Phase 2c entry); GitHub Run Tests is the gate.

## Execution Integrity Phase 4 — IaC fallback generation (2026-09-06)

Rule 4's runtime, first half (the `retry_queue` half is still deferred).
`services/iac_fallback.py` + `DevOpsAgent._iac_fallback`.

**Flow:** a creating tool returns `{'success': False}` →
`_verify_and_annotate` routes the failure to `_iac_fallback` →
`generate_cloudformation(tool_name, tool_input)` builds a compact CFN template
(JSON) from the same intent → attached as `_iac_fallback` on the result
(`{format, stack_name, template, resource_type, apply}`) →
`create_cloudformation_stack` appended to `_tools_override` so the model can
deploy it this turn. The `STABLE_SYSTEM_PROMPT` `IaC FALLBACK PROVIDED` line
tells the model to quote the real error, say a template is ready, and call
`create_cloudformation_stack` — not paste the template or send the user to the
console.

**Supported set:** `create_ec2_instance`/`run_instances` → `AWS::EC2::Instance`
(returns `None` without a concrete `ami_id` — CFN needs one too);
`create_security_group` → `AWS::EC2::SecurityGroup` (maps `ingress_rules` →
`SecurityGroupIngress`); `create_vpc` → `AWS::EC2::VPC`; `create_s3_bucket` →
`AWS::S3::Bucket`.

**`create_rds_instance` deliberately omitted** — `MasterUserPassword` would
land in the template artifact (chat/LLM/log path); a `NoEcho` parameter is the
right shape but deferred rather than risk it.

**Guards:** one `_iac_fallback` per turn (`_iac_fallback_emitted` greenlet-local,
reset in all 3 entry points); skipped in sandbox; kill-switch
`iac_fallback.enabled`; every exception path leaves the result untouched.
`iac_fallback.py` is pure — no boto3, never applies a template.

**Still deferred:** Terraform generation, the `retry_queue` DB table + worker,
RDS/IAM/networking-graph templates.

**Tests:** `tests/test_iac_fallback.py` (14 cases). Phase-4 + adjacent suites
green (219). Full local run 934 passed earlier this session.

## Execution Integrity Phase 5 — destructive-action hardening (2026-09-06)

The spec's v2.0 added three ⚠️ rules, all about deleting deeper and auditing it.

**Rule 3 — double-confirmation (`services/mutation_verifier.py`):** a
delete/terminate `_verification.status` is `confirmed` only after
`DELETE_CONFIRMING_READS = 2` **consecutive** live reads agree the resource is
gone/terminal; a `present`/`unknown` read resets the streak (tracked via a
closure counter in the delete `_poll` decide). Deletes use
`DELETE_BACKOFF = (0, 2, 5, 10, 20, 20)` (~57s — rule 2 v2's longer chain);
creates/updates keep `DEFAULT_BACKOFF`. The annotation carries
`reads: [<verdict per attempt>]` + `confirming_reads`. `_poll` now returns
`(verdict, elapsed, reads)`. On `unconfirmed` the message tells the agent to
**re-issue the terminate**; the prompt's `DELETE NOT CONFIRMED — RE-ISSUE`
line drives the terminate→verify→terminate loop. Platform never
auto-re-terminates.

**Rule 4 — mutation-verification pair log:** pairing already existed
(`_verify_and_annotate` runs the read-back in the same tool frame). Added
greenlet-local `_mutation_pairs` (one entry per verified mutation) +
`agent.last_mutation_pairs` + a `mutation-pair:` log line.

**Rule 10 — destructive audit trail (`_audit_infrastructure_change`):** the 5
executor sites were **reordered** — audit now runs *after*
`_verify_and_annotate` so it can read `result['_verification']`. Every
destructive row gets `change_details['audit_trail']` = `{timestamp,
user_confirmation, tool_request (via module-level `_redact_dict` — masks
password/secret/token/credential/private_key keys), tool_response,
verification (reads[]), final_confirmed_state (gone/still_present/unverified),
user_override_flag}`. A `gone` read followed by a non-`gone` sets
`change_details['audit_alert'] = 'verification_disagreement'` +
`destructive-audit-alert` warning.

**`record_state_override` tool (rules 9 + 10):** registered in `__init__`
alongside `search_tools`, added to `tool_selection.ALWAYS_TOOL_NAMES` (the
dispute can be about something verified turns ago).
`_record_state_override_handler(resource_id, corrected_state, evidence='')`
finds this user's most recent `InfrastructureChange` for the resource, sets
`audit_trail.user_override_flag = True` + `user_corrected_state`, `audit_alert
= 'user_override'`, `flag_modified` + commit. Low-risk (`record_` prefix).
Prompt's `STATE DISPUTES` line tells the model to call it on contradicting
console evidence.

**Tests:** `tests/test_destructive_verification.py` (16 cases). One existing
`test_mutation_verifier.py` delete test reworded for the new message. Adjacent
suites green (155 + 232). Full run pending.

## Scheduled audit (2026-09-06): sandbox mode could trigger a real destructive action; approved high-risk actions skipped audit/verification

Two gaps found in the human-approval workflow (`services/approval_service.py`,
the `ApprovalRequest`-backed path used whenever a non-approver/non-admin user
triggers a high/medium-risk tool — see "Admin Access" and the Safety System
section). Both live in code untouched by the Execution Integrity Phase 1/2/2b
work above, which is exactly why they'd been missed: those phases wired
`_audit_infrastructure_change`/`_record_tool_call`/`_verify_and_annotate` into
all 5 *model-driven* tool-execution sites in `core.py`, but never into the
approval workflow's own execution path.

**1. Sandbox Mode did not stop a real `ApprovalRequest` from being filed.**
At all three tool-loop sites in `core.py` (Kimi non-streaming, Kimi streaming,
Claude), `validation.requires_confirmation` was checked *before*
`self._sandbox_mode` — the opposite order from every other branch in the same
elif chain, which all check sandbox first. A plain `'user'`-role account with
Sandbox Mode enabled asking the agent to delete/terminate a resource therefore:
skipped the `elif getattr(self, '_sandbox_mode', False): ... generate_mock_result`
branch entirely; called `services.approval_service.create_request()`, writing a
real `ApprovalRequest` row and emailing a real approver/admin — with no sandbox
marker anywhere on the request (the `ApprovalRequest` model has no such column);
and, if approved, ran the tool for real via `_execute_tool()` against the
requester's actual cloud account. This broke Sandbox Mode's core guarantee
("Simulated tool results... not a substitute for a missing account" —
see CLAUDE.md's "Non-negotiable" section) for every confirmation-gated tool —
worse than fabricated data, since it's real infrastructure damage triggered by
what the user believed was a no-op simulation. Fixed by gating the
`requires_confirmation` branch on `and not getattr(self, '_sandbox_mode', False)`
at all three sites; sandbox mode now falls through to the existing sibling
`elif getattr(self, '_sandbox_mode', False):` branch unchanged. `routes/mcp.py`
and `routes/api_gateway.py`'s own `create_request` call sites were checked too —
neither has a sandbox concept at all (API-key/MCP tiers aren't tied to a chat
session's `UserPreferences.sandbox_mode`), so they were not in scope.

**2. `approval_service._execute_tool` (the approve-and-run path) skipped every
instrumentation call the same tool call would have gotten from a same-turn
self-confirmation.** It called `agent.tools[tool_name](**tool_input)` directly
with no `_audit_infrastructure_change` (no `InfrastructureChange` audit row —
and, for a destructive action, no purge from the synced-resource list, so a
terminated instance kept appearing "present" in the user's inventory/cost/drift
views until the next full sync), no `_record_tool_call` (invisible to
`usage_logs`/the `check-errors.yml` misrouting report), and no
`_verify_and_annotate` (an approved delete/terminate — precisely the highest-
risk tool class — got zero Execution Integrity read-back verification, unlike
the identical tool run from a same-turn self-approval). Root cause: those three
calls read `self._current_user_id`/`self._current_conversation_id`
(greenlet-local), which `_execute_tool` never set — only the cloud-credential
context (`_set_cloud_user_context`). Fixed by setting both alongside the cloud
context and clearing all three in the same `finally`, then calling all three
instrumentation functions around the real handler invocation, matching every
other execution site.

**Tests:** `tests/test_approval_credential_context.py` (new case: audit/record/
verify called in order, requester context visible during the call and cleared
after) and `tests/test_tool_call_observability.py` (new `TestSandboxNeverFilesRealApproval`:
Kimi non-streaming + streaming, asserts `approval_service.create_request` is
never called and the tool result comes back `simulated`-shaped). Full suite:
895 passed (1 pre-existing failure, `test_initialize_agent_populates_config`,
is an environment-only `ANTHROPIC_API_KEY` gap reproducible on the unmodified
`HEAD`, not a regression).

**Rebased onto main after Execution Integrity Phases 2c–5 landed (2026-09-06).**
Two adjustments to fix #2: (a) `_execute_tool` now calls
`_record_tool_call` → `_verify_and_annotate` → `_audit_infrastructure_change`
in that order (Phase 5 reordered the model-loop sites so the audit row can
read `result['_verification']` for the rule-10 destructive audit trail);
(b) `_execute_tool` resets the per-turn tool trackers first
(`_reset_turn_tool_state()`, extracted and now shared by all 4 tool-execution
entry points) — `_verify_and_annotate` reads greenlet-local `_verify_count`
(cap 3) / `_iac_fallback_emitted`, and a pooled gthread worker that ran a
chat turn earlier would otherwise carry stale values into the approval-run
and silently skip verification.

## Scheduled audit (2026-09-11): compound-qualifier prompt-injection regex bypass in `validate_message()`

Daily scheduled security review found no commits in the prior 26h, so ran the
rotating fallback audit (day-of-month mod 6) on `services/input_sanitizer.py`
+ `src/agent/guardrails.py`. Found and fixed a real regex gap in
`INJECTION_PATTERNS`'s ignore/forget/disregard entries — the three patterns
each allowed exactly **one** qualifier word between the verb and the
instructions-type noun (`ignore\s+(previous|above|all|prior)\s+(instructions?|...)`).
Verified live: `"ignore previous instructions"` was blocked, but
`"ignore all previous instructions"`, `"disregard all prior instructions"`,
and `"forget all your previous instructions"` — arguably the single most
common real-world jailbreak phrasing, and one of the Haiku screen's own
`SCREEN_SYSTEM_PROMPT` examples ("disregard all prior context") — all
bypassed the regex layer entirely, matching zero of the patterns.

This mattered more than a typical layer-1 miss because `validate_message()`'s
pattern list is documented above (see the "Guardrail screen fails open" row
in this file) as *"always the first line of defense"* — it is the only
deterministic check still active when `screen_message()`'s Haiku call is
skipped for lack of an `ANTHROPIC_API_KEY` (`guardrails.py`, returns
`blocked=False` immediately) or errors (fails open by design). In that
failure mode the compound-qualifier phrasing passed straight through with
zero blocking, other than the hardened system prompt in `core.py` (layer 3,
not audited in this pass).

**Fix:** `services/input_sanitizer.py` — replaced the single-qualifier group
in the `ignore`/`forget`/`disregard` patterns with a shared `_QUALIFIER`
alternation repeated `{1,3}` times (`\bignore\s+(?:{_QUALIFIER}\s+){1,3}(instructions?|...)`),
so any 1-3 word combination of `all|your|the|previous|prior|above` before the
noun is caught. Verified: all six previously-bypassed phrasings now blocked;
all four previously-caught phrasings still blocked (no regression); five
benign DevOps messages containing "previous"/"disregard"/"forget" as
ordinary English (e.g. "review the previous PR", "disregard the earlier
ticket") still pass — no new false positives from the wider qualifier group.

**Tests:** new `tests/test_input_sanitizer.py` (18 cases: compound-qualifier
bypass regression, single-qualifier no-regression, benign-message false-positive
check, plus basic `sanitize_input()` coverage). Full suite could not be run in
the audit sandbox (missing `flask`/app dependencies entirely — an environment
gap, not related to this change); the new test file's 18 cases pass in
isolation and no other test in the repo references `validate_message`,
`INJECTION_PATTERNS`, or `guardrails.screen_message` behavior.

**Not fixed in this pass, flagged for follow-up:** (1) `screen_message()`
(`guardrails.py`) only sends the first 3000 of the 10,000 chars
`validate_message()` allows to the Haiku classifier — a padded message can
push a paraphrased, non-regex-matching attack past the semantic screen's
view entirely. (2) `detect_crisis_language()` logs matched self-harm keyword
substrings verbatim via `logger.warning` with no redaction, into general
application logs rather than a purpose-built, access-controlled audit trail.

## Scheduled audit (2026-09-11), follow-up fix: Haiku semantic screen only saw the first 3000 of 10,000 allowed chars

Second fix from the same 2026-09-11 scheduled audit of `services/input_sanitizer.py`
+ `src/agent/guardrails.py` (the first fix, a compound-qualifier regex bypass
in `validate_message()`'s `INJECTION_PATTERNS`, is tracked separately — see
its own runbook entry / PR).

`guardrails.screen_message()` hardcoded `message[:3000]` when building the
prompt sent to the Haiku semantic classifier, even though `validate_message()`
— which every real call site runs immediately before `screen_message()` — allows
messages up to `MAX_MESSAGE_LENGTH` (10,000 chars, `services/input_sanitizer.py`).
Anything from char 3001 onward of an otherwise-valid message was invisible to
the one layer specifically designed to catch attacks that don't match a
literal regex (paraphrased jailbreaks, indirect social engineering, novel
out-of-scope-attack/malware-request phrasing). A message padded with ~3000
chars of benign filler before the actual ask would defeat the semantic screen
while still passing `validate_message()` unchanged.

**Fix:** import `MAX_MESSAGE_LENGTH` from `services.input_sanitizer` in
`src/agent/guardrails.py` and slice on that instead of the hardcoded `3000`,
so the semantic screen's window matches the ceiling `validate_message()`
already enforces rather than an independent, smaller one. Confirmed no
circular import (`input_sanitizer.py` has no dependency back into
`src/agent`). Verified behaviorally with a mocked Anthropic client: a marker
placed past the old 3000-char cutoff now reaches the classifier's prompt; a
marker placed past `MAX_MESSAGE_LENGTH` still does not (the slice is a
defense-in-depth ceiling matching the already-enforced bound, not an
unbounded pass-through — `screen_message()` can still be called directly,
e.g. in tests, without going through `validate_message()` first).

**Tests:** new `tests/test_guardrail_screen_length.py` (4 cases, mocked
`anthropic.Anthropic` client — no network calls: full-length message reaches
Haiku, message beyond `MAX_MESSAGE_LENGTH` is still capped, crisis detection
still short-circuits before Haiku, safe messages still pass). Full suite:
989 passed, 1 pre-existing failure (`test_initialize_agent_populates_config`,
an environment-only missing-`ANTHROPIC_API_KEY` gap already noted elsewhere in
this file as reproducible on unmodified `HEAD`, not a regression from this
change).

**Not fixed in this pass, still flagged for follow-up:** `detect_crisis_language()`
logs matched self-harm keyword substrings verbatim via `logger.warning` with no
redaction, into general application logs rather than a purpose-built,
access-controlled audit trail.

## Scheduled audit (2026-09-11), third fix: crisis keywords logged in plaintext to general application logs

Third finding from the 2026-09-11 scheduled security audit of
`services/input_sanitizer.py` + `src/agent/guardrails.py` (finding #1, a
regex bypass, and finding #2, a truncated semantic screen, are tracked
separately in their own PRs — all three are independent).

`guardrails.screen_message()` logged the verbatim matched self-harm keyword
text on every crisis detection: `logger.warning(f"Crisis language detected.
severity={crisis_severity} keywords={list(crisis_keywords.keys())}")`. That
logger writes to general application logs (`journalctl`/`logs/agent.log`/
whatever aggregator ingests them in production) — a much broader-access,
longer/less-deliberately-retained channel than the purpose-built store this
data already has: `CrisisIncident` (`models.py`), an explicit "audit trail —
logs when crisis language is detected" table, populated from
`GuardrailResult.crisis_keywords` at all three real call sites (`app.py` x2,
`routes/curriculum.py`) and only readable through `/api/admin/crisis-incidents`,
which does check `current_user.role != 'admin'` before returning anything.
Those three call sites' own `logger.warning()` lines were already clean
(`user_id`+`severity` only, no keyword text) — only the one inside
`guardrails.py` itself leaked the raw phrases.

**Fix:** log `severity` + `matched_keyword_count` (an integer) instead of the
keyword list. `GuardrailResult.crisis_keywords` is untouched — it still
carries the full dict through to `CrisisIncident.crisis_keywords`, which is
the intended, access-controlled home for this data; only the redundant,
broader-access copy in the plain log line is gone.

**Tests:** new `tests/test_crisis_keyword_log_redaction.py` (3 cases, using
pytest's `caplog`): the matched phrase never appears in log output;
`GuardrailResult.crisis_keywords` still carries it (so the audit-trail path
is unaffected); severity is still logged for ops-level visibility. Existing
`tests/test_crisis_detection.py` (25 tests) passes unchanged. Full suite:
970 passed, 1 pre-existing failure (`test_initialize_agent_populates_config`,
the same environment-only missing-`ANTHROPIC_API_KEY` gap noted elsewhere in
this file — not a regression).

## Scheduled audit (2026-09-15): git-clone flag injection, six safety.py risk gaps; several open items flagged for follow-up

Four parallel review passes: the three 2026-09-11 guardrail commits above,
`src/tools/git_tools.py`'s flag-injection guard coverage (the class fixed
three times before — see its section higher up), `safety.py`'s risk
classification against the full ~746-tool catalog, and a sweep for
fabricated-data/missing-user-filter patterns. Fixed the concrete,
mechanically-verifiable findings below; the rest need design judgment and are
recorded here rather than patched blind.

**Fixed — `git_clone_repository`'s `dest_path` was the one bare-positional
git-tool parameter never covered by `_reject_flag_like()`.** `url` is SSRF/
allowlist-validated and `branch`/`depth` become option *values*, but
`dest_path` (fully caller-controlled, required in the tool's `input_schema`)
went straight into `Repo.clone_from(url, dest_path, ...)` as the trailing
positional of `git clone <options> <url> <dest_path>`. git's option parser
permutes — a flag-shaped positional after the URL is still parsed as an
option — so `dest_path="--config=core.hooksPath=/tmp/h"` runs
attacker-chosen `post-checkout`/`post-merge` hooks *during the clone itself*;
`--template=/tmp/t` copies arbitrary hooks into the new `.git/hooks`;
`--separate-git-dir=/path` is an arbitrary directory/file write. GitPython's
own `unsafe_git_clone_options` check doesn't cover this: it only inspects
`kwargs`/`multi_options`, never the positional `to_path`, and is disabled
outright here anyway (`allow_unsafe_options=True`, needed for the
`-c http.followRedirects=false` SSRF fix in the same function). Fixed with
one `_reject_flag_like(dest_path, 'dest_path')` call before `Repo.clone_from`
— same pattern as every other guarded function in the file. New test:
`tests/test_git_tools_argument_injection.py::test_clone_rejects_flag_like_dest_path`
(mocks `_validate_git_url` so the case isolates the `dest_path` check from
DNS/network behavior). Every other function in the file that passes a
caller-supplied value to a git subprocess call was walked by hand and is
either already guarded, guarded via `--` pathspec termination, a pure option
*value* (never a leading positional), or never reaches a git subprocess at
all — no other gap found. Also fixed in the same pass: `git_create_tag`'s
`ref=commit` with `commit=None` stringified to the literal `"None"` instead
of defaulting to HEAD (`ref = commit or 'HEAD'`) — a correctness bug, not
security, caught while reading the function.

**Fixed — six tools with no confirmation gate despite a `provider_verb_noun`
shape that defeats the `delete_`/`terminate_`/... prefix auto-detector**
(the same recurring gap fixed on 2026-08-08/19/23/25 and 09-02): `high_risk_tools`
gained `list_storage_account_keys` (Azure — returns the raw storage-account
access key, a full data-plane credential, into the chat/tool-trace/LLM path;
same disclosure class as `get_secret_value`/`create_ec2_keypair`, and the
mutating sibling `regenerate_storage_key` was already gated but not this
read) and `terraform_state_pull` (returns the entire state file, which
routinely holds plaintext secrets — its `_push`/`_move`/`_rm` siblings were
already classified). `medium_risk_tools` gained `send_sqs_message` (same
"pages a live downstream consumer with caller-controlled content" shape as
the already-medium `publish_sns_message`/`publish_pubsub_message`),
`pagerduty_add_note` and `opsgenie_add_note` (post caller-controlled content
onto a live incident/alert; every sibling verb in the same module was
already medium), and `git_stash_save` (the one stash operation that actually
discards working-tree state — `git_stash_apply`/`git_stash_drop` were
already medium, the destructive one wasn't). Verified each classification
takes effect via `SafetyValidator.validate_tool_call(name, {})`.

**Not fixed — flagged for a follow-up change, not patched in this pass:**

- **The 2026-09-11 injection-regex fix (`f591c87`) closes the reported
  example, not the bypass class.** Live-verified current bypasses:
  `ignore any/every previous instructions` (qualifier set gap), `ignore all
  of the previous instructions`, punctuation between qualifiers
  (`ignore all, previous instructions`), and — pre-existing, same class —
  Unicode confusables surviving NFC-only normalization (fullwidth `ｉgnore`,
  Cyrillic `ѕ`). The same commit's added `the` qualifier now also blocks
  legitimate messages (`ignore the context`, `ignore the rules` — both
  ordinary Kubernetes/security-group vocabulary), each one burning a
  `record_guardrail_violation()` strike toward the 3-strike lockout.
- **`src/agent/guardrails.py:330`'s Haiku pre-screen interpolates the raw
  message inside `<message>…</message>` with no escaping** — a message
  containing a literal `</message>` can close the tag and append its own
  instruction to the classifier, undermining the screen the 09-11 commit
  widened the window of.
- **`c28c259`'s crisis-log redaction removed the only trace of crisis
  language on 4 of 6 call sites.** Its rationale (already captured in
  `CrisisIncident`) holds for the 3 sites wired to that model
  (`app.py:2898`, `app.py:3545`, `routes/curriculum.py:192`) but not
  `api/v1/conversations.py:310`/`:502` or `routes/api_gateway.py:711`/`:863`,
  which never create a `CrisisIncident` row — on those surfaces a user in
  crisis now gets a generic content-policy violation strike with no record
  anywhere that crisis language was involved.
- **`services/analytics_service.py` is still exactly the fabricated-data bug
  flagged (not fixed) on 2026-09-02** — `_ensure_sample_data()` generates 90
  days of cost/resource/incident data from `random.uniform/randint/choices`
  plus hardcoded `_cost_by_service`/`_cost_by_team` dicts, never consulted
  against `user_id` or any credential; `CostForecast.generate_forecast` adds
  `random.uniform` noise and reports a confidence score computed over that
  fake series. Four consumer templates (`analytics/dashboard.html`,
  `costs.html`, `performance.html`, `resources.html`) render it with no
  sandbox/no-account guard. **Same bug class found in three more places, not
  previously flagged:** `services/performance_optimizer.py`'s
  `_generate_sample_recommendations()` (seeds the literal `i-0abc123def456`
  fake instance id from the 2026-08-12 drift incident, for every user, at
  `/optimization/`), `services/ai_infrastructure.py`'s `get_recommendations()`
  (hardcoded list ignoring `user_id`) and `apply_recommendation()` (reports
  `success: True` without calling any cloud API — the same fake-Apply shape
  as the fixed predictive-scaling bug), and `services/chatops_service.py`'s
  `_cmd_metrics`/`_cmd_oncall` (hardcoded metrics/on-call roster delivered
  into Slack as live data). All deferred: fixing analytics_service.py alone
  needs its 4 templates read first per the existing note; the newly-found
  ones need the same treatment and are large enough to warrant their own
  reviewed change.
- **Latent (not currently reachable, same shape as the twice-fixed
  `compliance_service` bug):** `services/api_gateway.py`'s `get_api_key`/
  `get_webhook` and `services/multi_tenancy.py`'s `get_organization`/
  `get_team` are bare `Model.query.get(id)` despite an instance-level
  `self.user_id` — every current caller happens to pass its own `user_id`
  filter or sits behind a membership check, so nothing is exploitable today,
  but a future caller that omits that filter reopens the cross-tenant read
  this class of bug already caused twice.

## Scheduled audit (2026-09-13): ChatOps `/metrics` and `/oncall` fabricated data; `/status` silently showed 0 for two real counters

Routine review of `src/tools/`, `services/`, and `routes/` for vulnerabilities,
smells, and duplication. Grepped for the standing fabrication tells this repo
already tracks (`# In a real implementation`, `random.uniform`/`random.randint`
outside `learning_sandbox.py`'s intentional mock generator) and found two more
in `services/chatops_service.py`'s `_cmd_metrics` and `_cmd_oncall` — the same
file that had its per-user-arity `TypeError`s fixed the day before (2026-09-12,
see the SonarQube entry above), but this bug was invisible to that pass because
it never raises: it's a silent wrong-data bug, not a crash.

Unlike every sibling command in the file (`_cmd_status`, `_cmd_incidents`,
`_cmd_alerts`, `_cmd_playbooks`, ...), which all call `_require_app_user()` and
read real per-user state from `incident_response`/`proactive_monitoring`,
`_cmd_metrics` took no user argument at all and returned a fixed block of
invented numbers ("CPU Utilization: 45% (avg)", "Request Rate: 1.2k/min",
"Replication Lag: 0ms") to every account running `/metrics` in Slack or Teams.
`_cmd_oncall` did the same for a fake on-call roster ("Primary: @devops-team",
"Secondary: @sre-team") on every `/oncall`. Both are exactly the class of bug
CLAUDE.md's "Non-negotiable: every feature runs against a real cloud account"
section exists to catch — canned output indistinguishable from a real query —
just for chat-command status instead of a dashboard.

Separately, `_cmd_status` read `mon_status.get('active_rules', 0)` and
`mon_status.get('alerts_count', 0)`, but `ProactiveMonitoringService.get_status()`
returns `rules_enabled` and `alerts_active` — neither key `_cmd_status` read
has ever existed in that dict, so "Active Rules" and "Active Alerts" silently
displayed 0 in every `/status` reply regardless of the account's real counts.
`.get(key, default)` swallows the typo with no exception, which is why Sonar's
arity-mismatch scan (S930) didn't catch this one either.

**Fix (`services/chatops_service.py`):**
- `_cmd_status` now reads `rules_enabled` / `alerts_active`, the keys
  `get_status()` actually returns.
- `_cmd_metrics` now calls `_require_app_user()` and lists the caller's real
  configured monitoring rules from `ProactiveMonitoringService.get_rules()`
  (name, source, last collected value, state, threshold) with the same
  `service_filter` argument now matching against rule name/labels. An account
  with no monitoring rules configured gets an honest "no monitoring rules are
  configured" message instead of invented numbers — fail closed, not fake
  data, matching the pattern already used by Drift Detection and Predictive
  Scaling for the same underlying rule.
- `_cmd_oncall` now says plainly that no live PagerDuty/OpsGenie on-call is
  connected, rather than showing a schedule that was never true for any real
  account. There is no per-user PagerDuty/OpsGenie credential store the way
  there is for AWS/Azure/GCP (`UserCloudCredential`) for this command to read
  safely — `pagerduty_list_oncalls`/`opsgenie_get_oncall` in
  `alerting_tools.py` take a caller-supplied `api_key` or fall back to a
  single app-wide env var, neither of which is the right credential source
  for a per-tenant chat command — so building a real integration here is left
  as a follow-up rather than reusing the wrong credential model under audit
  time pressure.

**Not fixed in this pass, already flagged in CLAUDE.md and still open:**
`services/analytics_service.py`'s Advanced Analytics Dashboard (hardcoded
per-service/per-team cost breakdowns, a cost forecast built on
`random.uniform()` noise) — same fabrication class, larger surface (needs its
4 consumer templates read first per the existing note), intentionally left to
its own reviewed change rather than folded into this drive-by fix.

**Tests:** new `tests/test_chatops_fabricated_data.py` (5 cases, no Flask/app
import required — mocks `get_monitoring_service`/`get_incident_engine`
directly): `/metrics` with no rules configured reports honestly and contains
none of the old static numbers; `/metrics` with a real rule shows its actual
name/source/value and still contains none of the old static numbers;
`/metrics` raises `_UnresolvedAppUser` with no caller identity, like every
other per-user command; `/oncall` no longer mentions the fake `@devops-team`/
`@sre-team` names; `/status` reports the real `rules_enabled`/`alerts_active`
values instead of always 0. Could not run the full suite in this audit
environment (missing `flask`/`bcrypt` and the rest of the app's dependency
tree, the same environment gap noted in the 2026-09-11 audit entries above) —
the new test file imports only `services.chatops_service` directly and passes
in isolation; no other test in the repo references `_cmd_metrics`/`_cmd_oncall`
or `ProactiveMonitoringService.get_status()`'s exact key names.

## Scheduled audit (2026-09-19): `services/analytics_service.py` fabricated every Advanced Analytics Dashboard metric — fixed

Routine "review code for vulnerabilities, smells, duplicates" audit. CLAUDE.md's own "every
feature runs against a real cloud account" section already flagged this file back on 2026-09-02 as
found-but-not-fixed ("needs its 4 consumer templates read first"), so this pass read the 4
templates (`templates/analytics/dashboard.html`, `costs.html`, `resources.html`,
`performance.html`) and `routes/analytics.py`, confirmed the fabrication was still live, and fixed
it.

**What was wrong:** `AnalyticsService._ensure_sample_data()` built 90 days of `random`-seeded
cost/resource/incident/deployment history on first access and cached it for the life of the
instance; `_cost_by_service`/`_cost_by_team` were hardcoded dicts (`EC2: 450.00, RDS: 280.00, ...`,
`Development: 380.00, ...`); `CostForecast.generate_forecast()` added `random.uniform(-0.05, 0.05)`
variance on top of that already-fake history. Every one of the 12 `/analytics/api/*` endpoints in
`routes/analytics.py` read through this, so every logged-in user — regardless of whether they had
a cloud account connected at all — saw the exact same invented cost breakdown, forecast, resource
count, incident count, and deployment count. This was also reachable externally via the paid
developer REST API (`routes/api_gateway.py`'s `/v1/analytics/costs` → `get_cost_analytics()`), so a
third-party integration built on top of this API was making decisions on fiction too.

**The fix wires it to data this app already collects for real, some of it via a module
(`services/cost_explorer.py`) that already does real AWS Cost Explorer/CloudWatch calls elsewhere
(`app.py`'s `/api/dashboard/costs`, `src/tools/devops_operations_tools.py`) but was never
connected to this file:**
- Cost breakdown/forecast: `cost_explorer.get_actual_costs()`/`get_cost_forecast()` (real AWS Cost
  Explorer) first; on failure (no credentials, non-AWS account, API error), the same DB fallback
  `/api/dashboard/costs` already uses — sum `InfrastructureResource.monthly_cost` grouped by
  `resource_type` for that user. Both paths are real; a `source` field (`cost_explorer` |
  `database`) says which one answered.
- `CostForecast` keeps its linear-regression projection (a legitimate method) but now runs it over
  the real daily-cost history above, with the `random.uniform()` variance line deleted — identical
  input now produces identical output, not a different fake number on every request.
- Resource count/utilization: `InfrastructureResource` filtered to this user and non-terminated
  statuses (same exclusion list `services/infrastructure_sync.get_dashboard_summary()` uses).
  `utilization_avg` now samples real CloudWatch CPU (`cost_explorer.get_instance_utilization()`)
  across up to 5 running EC2 instances and averages them; with none available it's `0.0`, never a
  plausible-looking invented percentage.
- Incidents: real `IncidentModel` rows for the user, grouped by `severity`/`status`, trended
  against the prior period of the same length.
- Deployments: this app has **no dedicated Deployment model**, so rather than invent one, deploy
  activity is now counted from real `UsageLog` rows whose `tool_name` is a CI/CD trigger/apply tool
  (`trigger_jenkins_job`, `trigger_github_workflow`, `trigger_gitlab_pipeline`,
  `rerun_failed_github_jobs`, `deploy_cloud_run_service`, `docker_compose_up`, `terraform_apply`) —
  a real proxy for deployment activity, not a random count. `avg_duration_minutes` (previously
  `random.uniform(5, 20)`) is dropped entirely rather than approximated, since `UsageLog` has no
  duration column and no template reads that field.
- `by_team` cost attribution has no real backing data anywhere in this schema (no per-team cost
  tracking exists) — left honestly empty rather than reintroducing a hardcoded
  Development/Production/Staging/Testing split. No template reads it.

All 4 templates already degrade gracefully on empty data (`data.x || 0`, `if (labels.length)`
guards before building any chart), confirmed by reading each one first — so a disconnected account
now renders as zeros/"No Data" instead of requiring template changes.

**Tests:** new `tests/test_analytics_service.py` — empty-account-returns-zeros for every metric,
real per-user rows produce the right numbers *and* stay isolated from a second user's rows in the
same tables (regression guard for the user-isolation rule elsewhere in this file), and
`CostForecast` produces byte-identical output for identical input twice in a row (regression guard
against the removed `random.uniform()` call). Verified directly with a standalone script against
`models.py` + `services/analytics_service.py` under a real Flask/SQLAlchemy app context and
in-memory SQLite (this sandbox has no project dependencies installed beyond that, so the full
`pytest` suite — which imports the whole `app.py`, including boto3/anthropic/stripe/etc. — could
not be run here; same environment limitation noted in the 2026-09-11 entries above). The new test
file follows the existing `app`/`db_session`/`test_user` fixture pattern from `tests/conftest.py`
and should be run in CI to confirm.

**Not changed in this pass:** the resource-count time series (`_series_resource_count`) derives a
running total from each resource's `created_at`, which only reflects resources still on record —
one that was synced and later removed drops out of the historical total rather than showing a dip.
This is an honest limitation of not maintaining a historical resource-count table, not a
fabrication, and is called out in the method's docstring.

## Scheduled audit: `create_cloudformation_stack` unclassified; Execution Integrity's own audit trail has three unwired bypass paths (2026-09-07)

Routine audit of the ~3200-line Execution Integrity feature (Phases 1-5, merged
2026-09-05/06, never audited before this pass). `python3 scripts/check_security_invariants.py`
was clean; all six new greenlet-local fields, `tool_cache.py`'s per-user keying, and the
delete-verification fail-closed logic all checked out correct. Two real findings:

**Fixed — `create_cloudformation_stack` had no risk classification.** Same shape as the
`create_route53_record`/alerting-tool gaps found by earlier audits: `create_` isn't a
monitored auto-detect prefix, and its `delete_cloudformation_stack`/`update_cloudformation_stack`
siblings were already classified (high/medium) but the create path was missed. It accepts a
caller-supplied `template_body` plus `capabilities` including `CAPABILITY_NAMED_IAM` — the
same IAM-provisioning risk class `create_iam_role`/`create_iam_policy` are gated for — and
Phase 4's `_iac_fallback` now actively appends it to the model's offered tools on every failed
create, so leaving it low-risk made it a systematic *unconfirmed* recovery path, not just a
theoretical gap. Added to `medium_risk_tools` in `src/agent/safety.py` (see that file's own
comment for the reasoning) with a regression test in `tests/test_new_tools.py`
(`test_create_cloudformation_stack_is_medium_risk`). Also refreshed a stale comment in
`core.py`'s `_greenlet_local_property` docstring that still described the pre-#141 gevent
worker config instead of the current `gthread`/3-workers/8-threads setup.

**Flagged, not fixed — three tool-execution paths bypass the entire Execution Integrity
stack.** `services/approval_service.py`'s `_execute_tool()` (the approve-and-run path for a
previously-deferred high-risk call — by definition the highest-risk tool calls in the system),
`routes/api_gateway.py`'s `api_execute_tool()` (`/v1/execute` developer API), and
`routes/mcp.py`'s `_handle_tools_call()` (MCP connector) all call the tool handler directly
(`agent.tools[name](**args)` / `all_tools[name]['handler'](**params)` / `tool['handler'](**args)`)
instead of going through `DevOpsAgent._invoke_tool` → `_verify_and_annotate` →
`_audit_infrastructure_change`. All three already had `_set_cloud_user_context` wired in from
an earlier fix, but none received the Phase 2-5 verify/audit/cache wiring when it shipped.
Concrete impact: an approved `terminate_ec2_instance` can report `success: True` while the
instance is still `shutting-down`, with no read-back, no `_verification`, and no
`change_details.audit_trail` row — the exact guarantee Phase 5 exists to provide for
destructive actions — and the approving user's `READ_CACHE` entries are never invalidated, so
a stale pre-approval read can still be served for up to 60s afterward. This is the same
"duplicated logic not ported to sibling call sites" shape as the guardrails pipeline gap
documented above (8 hand-copied call sites) — not fixed in this pass because routing three
separate execution surfaces through the verify/audit/cache pipeline touches the approval flow,
the developer REST API, and the MCP connector at once, and deserves its own reviewed PR rather
than a drive-by edit during a read-mostly audit.

## Scheduled audit: `manage_ec2_instance` terminations bypassed the Phase 5 audit trail entirely; `send_sqs_message` unclassified (2026-09-09)

**`manage_ec2_instance(action='terminate')` produced zero `InfrastructureChange`
audit row.** `_audit_infrastructure_change`'s `is_destructive` check
(`src/agent/core.py`) was `tool_name.startswith(self._DESTRUCTIVE_PREFIXES)` —
literal prefix match only. `manage_ec2_instance` is the action-aware tool
CLAUDE.md documents as escalating to **CRITICAL** risk on a production
terminate, and `services/mutation_verifier.py`'s `_DELETE_SPECS` already
verifies it as a delete when `action=='terminate'` (Phase 2b) — but the
Phase 5 audit-trail function never got the same action-aware treatment, so it
returned early before writing anything. Net effect: terminating an instance
through the platform's primary EC2 management tool got no
`change_details.audit_trail`, no `verification_disagreement` alert even if
reads flipped present→gone→present, the terminated instance was never purged
from the synced `InfrastructureResource` inventory, and `record_state_override`
had no row to flag if a user disputed the outcome — the exact rule 9/10
recovery path Phase 5 (2026-09-06) was built to provide, silently inert for
this one tool. Root cause: the new Phase 5 code was gated on the
pre-existing, tool-name-only `is_destructive`, and nobody re-checked it
against the action-aware tools `manage_ec2_instance`/`manage_vm`/
`manage_compute_instance` that `safety.py` and `mutation_verifier.py` already
special-case elsewhere.

**Fixed** by computing `_manage_action`/`is_manage_terminate`/
`is_manage_update` from `tool_input['action']` when `tool_name ==
'manage_ec2_instance'`, folding `is_manage_terminate` into `is_destructive`
(with its own `resource_type = 'ec2'` branch, since the generic prefix-strip
slug logic doesn't apply to this tool name), and adding a sibling `update`
branch for `start`/`stop`/`reboot` so those get an audit row too (matching
`mutation_verifier.py`'s own `_EC2_STATE_TARGET` mapping). `action='start'`
still gets no audit row — same low-risk/no-confirmation treatment it already
has in `safety.py`.

**Also fixed, same pass:**
- `_redact_dict` (`src/agent/core.py`) only recursed into nested dicts, not
  dicts nested inside list-valued params — a secret-shaped field inside a
  list would have passed into the persisted rule-10 `audit_trail` unredacted.
  Not triggered by any current destructive-tool field, but the audit trail is
  read by humans, so hardened while this function was already being touched.
- `send_sqs_message` (`src/tools/aws_tools.py`) was missing from
  `medium_risk_tools` — same shape as `publish_sns_message`/
  `publish_pubsub_message` (arbitrary caller-controlled message content to a
  live external sink with no confirmation; `send_` isn't an auto-detected
  prefix), just never caught by the sweeps that added those two. Added to
  `medium_risk_tools` in `src/agent/safety.py`.

**Not fixed this pass, flagged for a dedicated change:** `services/chatops_service.py`'s
`_cmd_metrics`/`_cmd_oncall` (the `/metrics` and `/oncall` ChatOps slash
commands) return fully hardcoded literal values as if they were live
Prometheus/CloudWatch metrics and a live PagerDuty/OpsGenie on-call schedule,
with no `[Sandbox]` label — the same "canned output indistinguishable from a
real query" bug class as the Drift/Predictive Scaling/Analytics incidents
above, in a file not previously flagged. `services/analytics_service.py`'s
`random.uniform`/`random.choices`-based cost forecast and utilization/incident
data (flagged 2026-09-02, still unfixed) is also still live and unconditional.
Both need their consumer surfaces wired to this app's existing real
integrations (`monitoring_tools.py`, `alerting_tools.py`, `cost_explorer.py`)
rather than a drive-by fix during an audit pass.

**Tests:** existing `tests/test_execution_integrity.py`,
`tests/test_destructive_verification.py`, `tests/test_mutation_verifier.py`,
`tests/test_security_invariants.py` all green (81 cases) against the changed
code. Full suite: 953 passed / 11 failed, all 11 pre-existing environment gaps
unrelated to this change (missing `pyotp`/`googleapiclient` in this sandbox,
one flaky Stripe-config warning) — none touch `src/agent/core.py` or
`src/agent/safety.py`.

## Scheduled audit (2026-09-20): `services/performance_optimizer.py` fabricated every optimization recommendation; dashboard cost "Apply" reported fake success — both fixed

Routine code review. `python3 scripts/check_security_invariants.py` was clean. Two findings,
both the same "fail closed, never fabricate/fake-succeed" bug class documented throughout this
file and CLAUDE.md's standing rule — fixed the same way the Predictive Scaling and Analytics
fixes were.

**Fixed — `services/performance_optimizer.py` fabricated every recommendation shown at
`/optimization/` and `/optimization/recommendations`.** `_get_user_recommendations()` called
`_generate_sample_recommendations()` on first access for *any* user, unconditionally seeding
five hardcoded fake resources with invented dollar savings: `i-0abc123def456` (the same fake
EC2 id from the 2026-08-12 Drift incident and flagged again by the 2026-09-15 audit —
apparently never actually fixed despite being flagged twice), `prod-db`, `default/api-service`,
`vol-0xyz789`, `data-archive`. Every free/starter/pro/business user saw the byte-identical five
recommendations with byte-identical "Reduce monthly EC2 costs by approximately $150" style
claims regardless of what (if anything) was in their account — same shape as the Drift
`sg-12345` incident. Confirmed via grep that `analyze_resource()` (the method that takes real
`resource_data` and would produce a genuine recommendation) has zero callers anywhere in the
codebase — this feature was 100% fabricated end-to-end with no live wiring at all, not even a
partial one. Fixed by deleting `_generate_sample_recommendations()` and making
`_get_user_recommendations()` return an empty dict until a real caller wires up
`analyze_resource()` with live data — the identical fail-closed shape
`services/predictive_scaling.py`'s `generate_all_predictions()` already uses (empty until
`register_resource()`/`add_metric()` get real data; see that file's docstring, added in the
2026-09-02 fix). `templates/optimization/dashboard.html` already has a proper "No pending
recommendations" empty state, so no template change was needed. No test depended on the
fabricated data (`grep` found only unrelated reuses of the literal `i-0abc123def456...` as a
placeholder id in other services' test fixtures, e.g. `test_execution_integrity.py`,
`test_mutation_verifier.py` — none of them import `performance_optimizer`).

**Fixed — `app.py`'s `/api/dashboard/recommendations/<id>/apply` reported a fake "applied"
success with no cloud API call.** Unlike the recommendation-generation bug above, the
`CostOptimization` rows this endpoint operates on *are* real (`services/infrastructure_sync.py`'s
`generate_cost_recommendations()` already sources them from live CloudWatch data via
`services/cost_explorer.get_instance_utilization()`, per an earlier fix). The bug was narrower
but the same class as the Predictive Scaling "Apply" bug the 2026-09-02 audit fixed: the route's
own comment read `# For now, just mark as applied / # In production, actually execute the
action (stop instance, etc.)`, and it did exactly that — `recommendation.status = 'applied'`,
commit, return `success: True`. `templates/dashboard_live.html`'s `window._applyRec()` then
shows the user a `"Optimization applied - saving $X/mo"` success toast. Nothing ever called AWS
to stop, resize, or reconfigure anything — an idle EC2 instance flagged as `idle_resource` kept
running, still billing, while the user believed it had been handled and had no reason to check
again. Fixed to match `routes/scaling.py`'s `api_apply_recommendation` (fixed 2026-09-02):
returns `{success: false, error: "Applying this recommendation is not yet implemented — no
cloud API call is made...", ...}` with HTTP 501, and logs the refusal instead of silently
lying. No test covered this endpoint (`grep` for `apply_recommendation`/
`dashboard/recommendations` under `tests/` found nothing), so there was no regression risk in
tightening it.

**Still open, not touched by this pass:** `services/ai_infrastructure.py`'s
`get_recommendations()`/`apply_recommendation()` — the sixth and seventh known instances of
this same bug class per CLAUDE.md's running tally, flagged since 2026-09-15 and still
unfixed. Recommend a dedicated pass that also considers the structural fix CLAUDE.md now calls
for: a shared "no live account → fail closed" helper for recommendation generation, and a
shared "apply" helper that refuses to report success without an actual tool call, so this stops
recurring one service at a time.

## Scheduled audit (2026-09-24): ChatOps `/deployments` disclosed platform-wide webhook data with no auth check at all — fixed

Routine review of `src/tools/`, `services/`, and `routes/` for vulnerabilities, smells, and
duplication, run in four parallel passes: git/ansible argument-injection guards, the ChatOps
identity-linking and fabricated-action-claim wiring merged 2026-09-21 (PRs #193/#172), a grep
sweep for raw `requests.*`/`.check_password(`/fabricated-data/leaked-secret patterns, and
tool-capability staleness for newer tools. Three of the four passes came back clean (see below);
the ChatOps re-check of PR #193 found a real gap the PR's own description overstated.

**The bug.** `services/chatops_service.py`'s `_cmd_deployments` — unlike every other per-user
command in the file (`_cmd_status`, `_cmd_incidents`, `_cmd_metrics`, `_cmd_alerts`, ...) — never
called `_require_app_user()` at all. It called `get_webhook_service().get_events(event_type=
'deployment', limit=5)` directly, with no identity check of any kind. `WebhookEventRecord`
(models.py) has **no `user_id` column** — it's a single platform-wide table of CI/CD webhook
events (repository, branch, commit SHA, actor, title, description, URL), and every other reader
of it (`routes/webhooks.py`'s `webhooks_dashboard()` and `api_list_events()`) is correctly gated
`@login_required` + `@admin_required`. `_cmd_deployments` was the one path that skipped this
entirely: any Slack/Teams user who could message the bot — linked to an app account or not, and
regardless of platform role — could run `/deployments` and read every tenant's CI/CD history
platform-wide.

This also exposed a design gap PR #193's own CLAUDE.md description overstated: `ChatCommand`'s
`requires_auth` field (default `True`) is declarative only — `process_message()` never reads it.
Enforcement is entirely per-handler discipline (`_require_app_user(kwargs)` called at the top of
each handler that needs it), and nothing structurally catches a handler that forgets. This is the
same "duplicated pipeline, no shared enforcement point" shape already called out elsewhere in
CLAUDE.md for the guardrails pipeline and the CSRF/login-timing checks — a real fix would make
`requires_auth` load-bearing at dispatch time instead of trusting every handler to remember; not
done in this pass since it touches every command's calling convention at once.

**Verified as sound in the same pass:** the `/link <code>` redemption flow itself (8-char
alphanumeric code, 10-minute TTL, single-use via `used_at`, keyed to a platform identity that's
already authenticated upstream by Slack HMAC or Teams Bot Framework JWT before it ever reaches
`_cmd_link` — no way to link an arbitrary platform id without controlling that account); the
`_fabricated_action_claim()` wiring from PR #172 (`_UNIVERSAL_WRITE_TOOLS` names all still live
against the registry, both Kimi paths still call it before `_hallucination_severity`, no negation
bypass found — the only gap is a known coverage limit: verbs like "run the playbook"/"rotate the
key"/"cordon the node" match no `_ACTION_FAMILIES` request or claim regex, so a fabricated claim
phrased that way isn't checked; a pre-existing "known gap," not a regression); the git/ansible
argument-injection guards (every bare-positional caller-controlled parameter in `git_tools.py`
still calls `_reject_flag_like()`, and `ansible_tools.py`'s subprocess calls use list-form argv
with no shell=True and no unguarded flag-injectable parameter found); and the grep sweep (all 36
raw `requests.*` call sites are either `# ssrf-safe:`-exempted hardcoded hosts or already route
through `safe_request()`, zero `.check_password(` calls outside `routes/auth.py`, no new
fabricated-data patterns, and the AWS key removed by PR #208 has not recurred anywhere in the repo
including docs/).

**Fix (`services/chatops_service.py`):** `_cmd_deployments` now calls `_require_app_user()` like
every sibling handler, then loads the resolved user and requires `services.rbac.user_is_admin()`
before returning any webhook data — mirroring the web dashboard's own gate rather than inventing a
per-user view over data that was never partitioned per user. A non-admin (linked or not) gets a
plain refusal pointing at `/webhooks/` and the `/link` command; an unlinked identity is turned away
by `_require_app_user()` before the admin check ever runs, same as every other command.

**Tests:** new `tests/test_chatops_deployments_access_control.py` — unlinked identity refused
before dispatch; a linked non-admin `test_user` gets the admin-only refusal text and no webhook
data; calling the handler with no `app_user_id` raises `_UnresolvedAppUser` like every sibling
handler; a linked admin user is not turned away by the gate. Could not run the full suite in this
audit environment (dependency install was still in progress when this entry was written — see the
2026-09-11/2026-09-13 entries above for the same environment gap); the new test file follows the
same direct-handler-call pattern already used by `tests/test_chatops_fixes.py` and
`tests/test_chatops_fabricated_data.py`, both of which pass in isolation without the full app
context.
