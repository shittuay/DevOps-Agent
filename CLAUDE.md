# DevOps Agent - Claude Context

> This file provides persistent context for Claude Code sessions.

## Project Overview

**DevOps Agent** is a Flask-based web application that provides an AI-powered DevOps automation assistant. Users interact via chat to manage cloud infrastructure (AWS, Azure, GCP), Kubernetes clusters, and CI/CD pipelines.

## Tech Stack

- **Backend:** Flask + SQLAlchemy (SQLite)
- **Frontend:** Jinja2 templates + vanilla JavaScript
- **AI:** Kimi K2.5 (default, free/starter) + Anthropic Claude (professional/business)
- **Auth:** Flask-Login with bcrypt password hashing
- **Cloud:** boto3 (AWS), azure-sdk, google-cloud

## Key Architecture

```
app.py              # Flask application entry point
models.py           # SQLAlchemy models (User, Conversation, ChatMessage, etc.)
src/
  agent/
    core.py         # DevOpsAgent - main AI orchestration
    safety.py       # SafetyValidator - command/tool risk classification
    conversation.py # ConversationManager - message handling
    guardrails.py   # GuardrailsService - Haiku harmlessness pre-screen
  tools/
    aws_tools.py         # 154 AWS tools (EC2, VPC, IAM, RDS, Lambda, ECS, EKS, S3, etc.)
    kubernetes_tools.py  # 28 K8s tools (pods, deployments, services, namespaces, etc.)
    azure_tools.py       # 36 Azure tools (VMs, storage, SQL, NSGs, containers, etc.)
    gcp_tools.py         # 40 GCP tools (Compute, GCS, Cloud SQL, GKE, Cloud Run, etc.)
    git_tools.py         # Git operations
  config/
    config_manager.py
services/
  model_router.py          # Tier -> AI model mapping (free/starter=Kimi, pro=Sonnet, biz=Opus)
  model_failover.py        # KimiProvider, GroqProvider with health tracking
  chat_service.py          # Groq fallback chat, upgrade pitch, error detection
  credential_service.py    # Per-user AWS credential storage (dual-mode: access keys + role ARN)
  infrastructure_sync.py   # Per-user cloud resource sync
  credential_encryption.py # Fernet encryption for credentials
  input_sanitizer.py       # sanitize_input() + validate_message() (injection blocking)
  learning_sandbox.py      # Mock tool results for sandbox/learning mode
templates/
  chat.html, settings.html, etc.
```

## Tool Inventory (258 total)

### AWS (154 tools)
Full lifecycle management: EC2, VPC, IAM, RDS, Lambda, ECS, EKS, S3, DynamoDB, CloudFormation, Route53, SNS/SQS, SSM, CloudWatch, ElastiCache, EFS, EventBridge, Kinesis, NAT Gateway, Load Balancers, Target Groups, ECR, Secrets Manager, Service Quotas.

### Kubernetes (28 tools)
Pods (list, describe, logs, delete, exec), Deployments (list, describe, create, update image, delete), Services (list, create, delete), Namespaces (list, get, create, delete), ConfigMaps (create, delete), Secrets (create, delete), Ingress (create, delete), Nodes (list, cordon, uncordon), Jobs (create, delete).

### Azure (36 tools)
VMs (list, describe, start, stop, restart, create, delete), Storage (list accounts, create, delete, list keys, regenerate key), SQL (list servers, create server, delete server, delete database, firewall rules), NSGs (list, create, create rule, delete), Container Instances (list, create, delete, restart), Disks (list, create, delete), VNets (list, create), Public IPs (list, delete).

### GCP (40 tools)
Compute (list, describe, start, stop, create, delete, snapshots), GCS (list buckets, create, delete, list objects), Cloud SQL (list, create, delete, restart), GKE (list clusters, describe, resize, delete), Cloud Run (list, deploy, delete), Pub/Sub (list topics, create topic, delete topic, create subscription), Secret Manager (list, create, delete, add version), BigQuery (list datasets, create, delete), Firewall (list, create, delete), Cloud Functions (list, delete), Cloud Logs.

## Critical Security Patterns

### User Isolation (NEVER bypass)
- ALL database queries MUST filter by `user_id=current_user.id`
- Conversations, messages, credentials are per-user
- Cloud operations use per-user encrypted credentials

### Credential Storage
- `UserCloudCredential` model stores encrypted credentials
- Uses Fernet (AES-128) encryption via `credential_encryption.py`
- Key derived from `CREDENTIAL_ENCRYPTION_KEY` or `SECRET_KEY`
- **AWS dual-mode auth** (`credential_service.py`):
  - `auth_mode='access_key'`: Direct IAM access key + secret key (simple, for self-hosting teams)
  - `auth_mode='role_arn'`: IAM Role ARN + optional External ID → STS AssumeRole for temp creds (enterprise, cross-account)
  - `get_user_boto_client()` / `get_user_boto_resource()` handle both modes transparently
  - Settings UI (`templates/settings.html`) has toggle between the two modes

### Authentication
- `@login_required` decorator on all API routes
- Email verification required for new accounts
- Account lockout after 5 failed attempts

### Guardrails (Jailbreak / Prompt Injection Defense)
Three-layer stack applied at both `/api/chat` and `/api/chat/stream` before any credit is deducted:

1. **`validate_message()`** (`services/input_sanitizer.py`) — blocks messages with injection patterns (10 regex rules) and enforces a 10,000-char limit. Returns `(bool, reason)`.
2. **`screen_message()`** (`src/agent/guardrails.py`) — Haiku pre-screen using structured tool output. Classifies: `prompt_injection`, `out_of_scope_attack`, `malware_request`, `data_exfiltration`, `social_engineering`. Fails open on error.
3. **Hardened system prompt** (`src/agent/core.py`) — `SECURITY BOUNDARIES` section: fixed identity, no prompt disclosure, refuse malware generation, reject in-message operator impersonation.

**Violation tracking on `User` model:**
- `guardrail_violations` (Integer) + `guardrail_blocked_until` (DateTime)
- `record_guardrail_violation()` — increments counter; blocks for 1 hour after 3 violations
- `is_guardrail_blocked()` — auto-unblocks and resets counter after block expires
- Run `migrate_missing_columns.py` to add these columns to existing databases

## Safety System (`src/agent/safety.py`)

`SafetyValidator.validate_tool_call()` classifies every tool into risk levels:

- **high_risk_tools**: All delete/terminate operations across all providers. Requires user confirmation. Escalates to `critical` if targeting production.
- **medium_risk_tools**: Update, restart, firewall rule, IAM, scale, cordon operations. Requires user confirmation.
- **low risk** (default): Create and read operations. No confirmation needed.

**When adding new tools:**
- Every new `delete_*` or `terminate_*` tool MUST be added to `high_risk_tools`
- Every new `update_*`, `restart_*`, `create_*_rule`, or IAM tool MUST be added to `medium_risk_tools`
- Forgetting this causes the tool to default to low risk with no confirmation prompt

## Adding a New Tool

### General Steps
1. Create handler function in the appropriate `src/tools/*_tools.py`
2. Register in `get_tools()` at the bottom of the same file with `{name, description, input_schema, handler}`
3. Add to `safety.py` risk classification if delete/update operation
4. Verify: `python -c "from src.tools.X import get_tools; print(len(get_tools()))"`

### AWS Pattern
```python
def my_tool(param: str, region: Optional[str] = None) -> Dict[str, Any]:
    try:
        client = _get_boto_client('service_name', region)
        response = client.api_call(...)
        return {'success': True, 'message': '...', ...}
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}
```
- Always use `_get_boto_client()` — never create boto3 clients directly (uses thread-local per-user credentials)

### Kubernetes Pattern
```python
def my_tool(param: str, namespace: str = 'default', context: Optional[str] = None) -> Dict[str, Any]:
    try:
        v1, apps_v1 = _get_k8s_client(context)
        # For NetworkingV1Api or BatchV1Api, create inline:
        # networking_v1 = client.NetworkingV1Api()
        # batch_v1 = client.BatchV1Api()
        result = v1.api_call(...)
        return {'success': True, 'message': '...', ...}
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}
```
- `_get_k8s_client()` returns `(CoreV1Api, AppsV1Api)` only. For other API groups, create the client inline after calling the helper (it loads kubeconfig as a side effect).

### Azure Pattern
```python
def my_tool(param: str) -> Dict[str, Any]:
    try:
        client = _get_azure_client('service_type')  # compute|storage|network|resource|monitor|container|sql
        result = client.resources.begin_operation(...).result()  # .result() waits for async completion
        return {'success': True, 'message': '...', ...}
    except Exception as e:
        logger.error(f"Azure API error: {str(e)}")
        return {'success': False, 'error': str(e)}
```
- Most Azure write operations are async: use `begin_*()` which returns a poller, then call `.result()` to wait.

### GCP Pattern
```python
def my_tool(param: str, project_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        from google.cloud import specific_service_v1  # inline import
        project = _resolve_project_id(project_id)     # explicit > per-user > env var
        client = specific_service_v1.ServiceClient()
        result = client.api_call(request={...})
        return {'success': True, 'message': '...', ...}
    except Exception as e:
        logger.error(f"GCP API error: {str(e)}")
        return {'success': False, 'error': str(e)}
```
- Always use `_resolve_project_id()` — never hardcode project IDs.
- GCP clients are imported inline per function.

## Resolved Issues / Gotchas

| Issue | Solution |
|-------|----------|
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
| **Stripe price IDs not loading in production** | `MANAGED_SECRET_KEYS` in `secrets_manager.py` was missing Stripe price IDs. Added all `STRIPE_PRICE_*` and `STRIPE_PUBLISHABLE_KEY` to the list. Must also be added to AWS Secrets Manager JSON. |
| **Credit pack size mismatch** | Billing page showed packs of 50/200 but Stripe config has 100/250. Fixed billing.html to match Stripe: 100/$10, 250/$20, 500/$35, 1000/$60. |
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
| **`resolve_model_for_tier('free')` now returns Kimi** | Free and Starter tiers default to `kimi` provider. Use `resolve_model_with_preference(tier_name, preferred_provider)` to respect user overrides. The `provider` parameter on `process_message_isolated()` and `process_message_streaming()` routes to `_call_kimi_api()` when set to `'kimi'`. |
| **Kimi tool format differs from Anthropic** | Anthropic uses `{name, description, input_schema}`. Kimi (OpenAI-compatible) uses `{type: "function", function: {name, description, parameters}}`. `_convert_tools_to_openai_format()` in `core.py` handles the conversion. |
| **Kimi K2.5 rejects temperature != 1 (FIXED)** | K2.5 is a reasoning model that only accepts `temperature=1`. Passing `temperature=0.7` caused 400 errors. Fixed in `core.py`: skip temperature param when model contains `k2`. |
| **Kimi reasoning_content missing in tool calls (FIXED)** | Kimi K2.5 streams `reasoning_content` (thinking tokens) that must be preserved in assistant messages during multi-turn tool-use conversations. If omitted, subsequent API calls fail with "thinking is enabled but reasoning_content is missing". Fixed by collecting `reasoning_content` from streaming deltas and including it in the assistant message dict. |
| **AWS dual-mode auth (access keys + role ARN)** | `credential_service.py` supports both `auth_mode='access_key'` (direct keys) and `auth_mode='role_arn'` (STS AssumeRole with temp creds). Settings UI has toggle. Small teams use access keys; enterprise uses cross-account role delegation. |
| **11 missing DB columns caused 500 error (FIXED)** | New model fields (`preferred_model_provider`, `learning_mode`, `sandbox_mode`, `learning_level`, `email_verified`, `email_verification_token`, `email_verification_sent_at`, `password_reset_token`, `password_reset_expires`, `guardrail_violations`, `guardrail_blocked_until`) weren't in the DB. Fixed by running `migrate_missing_columns.py`. |
| **Env var name mismatch for Kimi (FIXED)** | `.env` had `kimi_API_KEY` but code reads `MOONSHOT_API_KEY`. Renamed in `.env`. |

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

## Free Trial System

Free-tier users get **20 credits/month** with the **full agent experience** — Kimi K2.5 with real tool execution (users can switch to Claude via the model toggle). This replaces the old Groq/Llama chat-only experience that had no tool support.

### Model Tier Mapping (`services/model_router.py`)

| Tier | Default Provider | Model | Tools | Max Tokens |
|------|----------|-------|-------|------------|
| free | Kimi | `kimi-k2.5` | Yes | 4096 |
| starter ($29/mo) | Kimi | `kimi-k2.5` | Yes | 4096 |
| professional ($99/mo) | Anthropic | `claude-sonnet-4-6` | Yes | 8192 |
| business ($299/mo) | Anthropic | `claude-opus-4-6` | Yes | 8192 |

**Users can override their tier default** via a toggle in the chat toolbar (`/api/model/switch`). The override is stored in `UserPreferences.preferred_model_provider` (null = tier default, `'anthropic'` = force Claude, `'kimi'` = force Kimi). Use `resolve_model_with_preference(tier_name, preferred_provider)` instead of `resolve_model_for_tier()` when you need to respect user preference.

### Kimi K2.5 Integration
- **Provider:** Moonshot AI, OpenAI-compatible API at `https://api.moonshot.ai/v1`
- **Model ID:** `kimi-k2.5` (262K context, ~$0.60/M input, ~$3.00/M output)
- **Auth:** Bearer token via `MOONSHOT_API_KEY` env var
- **Tool support:** Yes — all 258 tools work via OpenAI function-calling format
- **Implementation:** `KimiProvider` in `services/model_failover.py`, `_call_kimi_api()` and `_call_kimi_api_streaming()` in `src/agent/core.py`
- **Tool format conversion:** `_convert_tools_to_openai_format()` converts Anthropic `{name, description, input_schema}` to OpenAI `{type: "function", function: {name, description, parameters}}`
- **Fallback:** If Kimi fails, auto-falls back to Groq (same as Anthropic failure path)
- **Reasoning model constraints:**
  - K2.5 only accepts `temperature=1` — skip temperature param when model contains `k2`
  - Streams `reasoning_content` (thinking tokens) alongside `content` — must collect from deltas
  - `reasoning_content` MUST be preserved in assistant messages during multi-turn tool-use conversations or subsequent API calls fail with "reasoning_content is missing"

### Trial Context (`src/agent/core.py`)
- `trial_context` string is built in `app.py` / `api/v1/conversations.py` for free-tier users
- Threaded through `process_message_isolated()` → `_call_claude_api()` / `_call_kimi_api()` → `_build_system_prompt()`
- Appended to the system prompt so the agent knows the user is on trial
- When credits <= 5, the agent is instructed to naturally mention upgrading (without derailing the answer)

### Credit Exhaustion — Upgrade Pitch
- **Free-tier users** with 0 credits get a **200 response** with `generate_upgrade_pitch()` from `services/chat_service.py` (not a 402 error)
- `/api/chat`: returns `{response: "...", trial_ended: true, credits_remaining: 0}`
- `/api/chat/stream`: returns SSE with pitch as chunk + `{type: "done", trial_ended: true}`
- **Paid users** still get a normal `402` with `insufficient_credits` error
- Frontend (`index.html`) handles `trial_ended: true` by showing a styled "Upgrade to Starter" CTA button and disabling the input

### Groq Fallback (Anthropic/Kimi outage only)
- `process_free_tier_chat()` and `stream_free_tier_chat()` in `chat_service.py` use Groq/Llama as a **fallback** when both Anthropic and Kimi are down
- These functions use hardcoded `GROQ_FALLBACK_MODEL = 'llama-3.3-70b-versatile'` (NOT `resolve_model_for_tier('free')`, which now returns Kimi)
- All Groq fallback paths in `app.py` and `api/v1/conversations.py` use explicit `ModelConfig(provider='groq', ...)` instead of resolving the free tier
- `FREE_TIER_SYSTEM_PROMPT` is now labeled as a "fallback model" prompt — only used during Groq failover

### Learning Mode & Sandbox

Users can enable **Learning Mode** and/or **Sandbox Mode** in Settings > Preferences:

- **Learning Mode** (`UserPreferences.learning_mode`): AI explains DevOps concepts inline, tracks proficiency per topic via `LearningSession` model. API: `/api/learning/session-summary`, `/api/learning/history`, `/api/learning/proficiency`
- **Sandbox Mode** (`UserPreferences.sandbox_mode`): Tools return simulated results from `services/learning_sandbox.py` instead of calling real cloud APIs. Safe for experimentation. Covers AWS, K8s, Azure, GCP with realistic mock data.
- **Learning Level** (`UserPreferences.learning_level`): `beginner`, `intermediate`, `advanced` — controls explanation depth
- Settings UI shows proficiency radar and learning history when learning mode is enabled

### Cost
- ~$0.05/message with Sonnet 4.6 × 20 credits = **~$1.00/user/month**
- Worth it to convert a $29/mo Starter subscriber

## Billing & Stripe Payment Flow

### Architecture
- **Frontend:** `templates/billing.html` — subscription tiers + credit pack purchase buttons
- **Stripe Checkout:** `stripe_integration.py` — `StripePaymentService` handles session creation
- **Webhook:** `/api/stripe/webhook` in `app.py` — receives Stripe events, grants credits/subscriptions
- **Models:** `UserSubscription`, `CreditPurchase`, `SubscriptionTier`, `StripeWebhookEvent` in `models.py`

### Payment Flow (MUST follow this pattern)
1. User clicks upgrade/purchase on billing page
2. JS calls `/api/subscription/create-checkout` or `/api/credits/create-checkout`
3. Backend creates Stripe Checkout session, returns `checkout_url`
4. User redirected to Stripe's hosted payment page
5. After payment, Stripe sends `checkout.session.completed` webhook
6. `handle_checkout_completed()` verifies and grants subscription/credits
7. User redirected to `/billing/success` which shows billing page

### CRITICAL: Never grant credits without Stripe verification
- `/api/subscription/upgrade` — DISABLED (returns 403). Was a legacy endpoint that granted free subscriptions.
- `/api/credits/purchase` — DISABLED (returns 403). Was a legacy endpoint that granted free credits.
- Credits/subscriptions MUST only be granted via `handle_checkout_completed()` after Stripe webhook verification.

### Stripe Environment Variables (all required for payments)
- `STRIPE_SECRET_KEY` — Stripe API secret key
- `STRIPE_PUBLISHABLE_KEY` — Stripe publishable key (passed to billing template)
- `STRIPE_WEBHOOK_SECRET` — Webhook signature verification secret
- `STRIPE_PRICE_STARTER` — Stripe Price ID for Starter tier ($29/mo)
- `STRIPE_PRICE_PROFESSIONAL` — Stripe Price ID for Professional tier ($99/mo)
- `STRIPE_PRICE_BUSINESS` — Stripe Price ID for Business tier ($299/mo)
- `STRIPE_PRICE_PACK_100` — Price ID for 100-credit pack ($10)
- `STRIPE_PRICE_PACK_250` — Price ID for 250-credit pack ($20)
- `STRIPE_PRICE_PACK_500` — Price ID for 500-credit pack ($35)
- `STRIPE_PRICE_PACK_1000` — Price ID for 1000-credit pack ($60)

All Stripe env vars must be in AWS Secrets Manager (`devops-agent/production` JSON) for production.
They are listed in `services/secrets_manager.py` `MANAGED_SECRET_KEYS`.

## Environment Variables

Required:
- `ANTHROPIC_API_KEY` - Claude API key
- `SECRET_KEY` - Flask session secret

Optional:
- `CREDENTIAL_ENCRYPTION_KEY` - For credential encryption
- `DATABASE_URL` - Database connection string
- `STRIPE_SECRET_KEY` - Stripe payment processing (see Billing section above)
- `BASE_URL` - App base URL for Stripe callbacks (default: `https://devopsagent.io`)
- `MOONSHOT_API_KEY` - Kimi K2.5 API key (required for Kimi model provider)
- `KIMI_MODEL` - Kimi model override (default: `kimi-k2.5`)

## Running the App

```bash
python app.py  # Web UI at http://localhost:5000
python main.py interactive  # CLI mode
```

## Testing

```bash
pytest -q                    # Run all tests
python -m pytest tests/ -v   # Verbose
```

## Adding a New Model

1. Define in `models.py`
2. Run migration: `python migrate_*.py`
3. Add API routes in `app.py`

## Current User Context

Each user has isolated:
- Chat conversations and history
- Cloud credentials (AWS/Azure/GCP)
- Infrastructure resources
- Cost optimizations and alerts
- Subscriptions and credits

## Skills Available

Use `/skill-name` or mention the skill:
- `/flask-test` - Run tests
- `/db-migrate` - Database migrations
- `/deploy-verify` - Deployment verification
- `/cloud-debug` - Cloud troubleshooting
- `/devops-agent-dev` - Development guide
- `/secrets-mgmt` - Secrets management
- `/update-context` - Update CLAUDE.md after significant codebase changes
- `/resume-work` - Recover context and resume after rate limit or token reset
- `/continue-where-you-stop` - Automatically pick up and continue unfinished work after interruptions
- `/memory` - Maintain WORKLOG.md as persistent session memory across resets
- `/security-scan` - Run security scans (infrastructure, compliance, secrets, vulnerabilities, audit)

## Code Style

- No emojis unless requested
- Minimal comments (self-documenting code)
- Type hints for function signatures
- SQLAlchemy for all database operations
