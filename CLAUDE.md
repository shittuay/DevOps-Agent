# DevOps Agent - Claude Context

> This file provides persistent context for Claude Code sessions.

## Project Overview

**DevOps Agent** is a Flask-based web application that provides an AI-powered DevOps automation assistant. Users interact via chat to manage cloud infrastructure (AWS, Azure, GCP), Kubernetes clusters, and CI/CD pipelines.

## Tech Stack

- **Backend:** Flask + SQLAlchemy (SQLite)
- **Frontend:** Jinja2 templates + vanilla JavaScript
- **AI:** Anthropic Claude API
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
  model_router.py          # Tier -> AI model mapping (free=Sonnet 4.6, starter=Haiku, etc.)
  chat_service.py          # Groq fallback chat, upgrade pitch, error detection
  infrastructure_sync.py   # Per-user cloud resource sync
  credential_encryption.py # Fernet encryption for credentials
  input_sanitizer.py       # sanitize_input() + validate_message() (injection blocking)
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

Free-tier users get **20 credits/month** with the **full agent experience** — Claude Sonnet 4.6 with real tool execution. This replaces the old Groq/Llama chat-only experience that had no tool support.

### Model Tier Mapping (`services/model_router.py`)

| Tier | Provider | Model | Tools | Max Tokens |
|------|----------|-------|-------|------------|
| free | Anthropic | `claude-sonnet-4-6` | Yes | 4096 |
| starter ($29/mo) | Anthropic | `claude-haiku-4-5-20251001` | Yes | 4096 |
| professional ($99/mo) | Anthropic | `claude-sonnet-4-6` | Yes | 8192 |
| business ($299/mo) | Anthropic | `claude-opus-4-6` | Yes | 8192 |

### Trial Context (`src/agent/core.py`)
- `trial_context` string is built in `app.py` / `api/v1/conversations.py` for free-tier users
- Threaded through `process_message_isolated()` → `_call_claude_api()` → `_build_system_prompt()`
- Appended to the system prompt so the agent knows the user is on trial
- When credits <= 5, the agent is instructed to naturally mention upgrading (without derailing the answer)

### Credit Exhaustion — Upgrade Pitch
- **Free-tier users** with 0 credits get a **200 response** with `generate_upgrade_pitch()` from `services/chat_service.py` (not a 402 error)
- `/api/chat`: returns `{response: "...", trial_ended: true, credits_remaining: 0}`
- `/api/chat/stream`: returns SSE with pitch as chunk + `{type: "done", trial_ended: true}`
- **Paid users** still get a normal `402` with `insufficient_credits` error
- Frontend (`index.html`) handles `trial_ended: true` by showing a styled "Upgrade to Starter" CTA button and disabling the input

### Groq Fallback (Anthropic outage only)
- `process_free_tier_chat()` and `stream_free_tier_chat()` in `chat_service.py` use Groq/Llama as a **fallback** when Anthropic is down
- These functions use hardcoded `GROQ_FALLBACK_MODEL = 'llama-3.3-70b-versatile'` (NOT `resolve_model_for_tier('free')`, which now returns Anthropic)
- All Groq fallback paths in `app.py` and `api/v1/conversations.py` use explicit `ModelConfig(provider='groq', ...)` instead of resolving the free tier
- `FREE_TIER_SYSTEM_PROMPT` is now labeled as a "fallback model" prompt — only used during Groq failover

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

## Code Style

- No emojis unless requested
- Minimal comments (self-documenting code)
- Type hints for function signatures
- SQLAlchemy for all database operations
