# DevOps Agent - Runbook & Historical Fixes

> Historical bug fixes, resolved issues, and gotchas.\n> See CLAUDE.md for active development guidance.

This document archives fixed issues and their solutions for reference. Most issues here are already resolved in the codebase and documented in git history.

## Resolved Issues / Gotchas

| Issue | Solution |
|-------|----------|
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
