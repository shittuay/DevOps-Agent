---
name: inspect-fix
description: Comprehensive inspection of all DevOps Agent features — routes, services, models, templates, tools — with immediate error remediation. Use when you need a full health audit of the application.
---

# Full Feature Inspection & Remediation

Inspect every layer of the DevOps Agent application and fix any errors found immediately.

## Phase 1: Prerequisites

1. **Ensure PostgreSQL is running**:
   ```bash
   docker ps | grep devops-postgres
   ```
   If not running: `docker start devops-postgres`

2. **Kill any stale Python processes**:
   ```bash
   taskkill //F //IM python.exe 2>/dev/null
   ```

## Phase 2: Import & Module Validation

Check that all key modules import without errors. Run each check and fix any `ImportError`, `SyntaxError`, or `AttributeError` immediately.

### 2a. Core App
```bash
python -c "from app import app; print('app.py: OK')"
```

### 2b. Models
```bash
python -c "from models import db, User, Conversation, ChatMessage, UserSubscription, SubscriptionTier, UserPreferences, UserCloudCredential, APIKey, InfrastructureResource, CostOptimization, Alert, MonitoringRuleModel, MonitoringAlertModel, IncidentModel, PlaybookModel, AnalysisModel, AuditLog, SecurityFinding, ComplianceFrameworkModel, CompliancePolicy, ComplianceReport, Organization, OrganizationMember, Team, TeamMember, InfrastructureTemplate, ProvisioningRequestModel, CommandTemplate, BudgetAlert, ResponseFeedback, WebhookEndpoint, WebhookDelivery, InfrastructureChange, UsageLog, CreditPurchase, StripeWebhookEvent, PaymentWebhookEvent, NGNPriceConfig, UserNotificationChannel, UserMemory, LearningSession, ContactMessage; print('models.py: OK')"
```

### 2c. Agent Core & Safety
```bash
python -c "from src.agent.core import DevOpsAgent; print('agent/core.py: OK')"
python -c "from src.agent.safety import SafetyValidator; print('agent/safety.py: OK')"
python -c "from src.agent.guardrails import GuardrailsService; print('agent/guardrails.py: OK')"
python -c "from src.agent.conversation import ConversationManager; print('agent/conversation.py: OK')"
```

### 2d. All Tool Modules (258 tools)
```bash
python -c "
from src.tools.aws_tools import get_tools as aws; print(f'AWS: {len(aws())} tools OK')
from src.tools.kubernetes_tools import get_tools as k8s; print(f'K8s: {len(k8s())} tools OK')
from src.tools.azure_tools import get_tools as az; print(f'Azure: {len(az())} tools OK')
from src.tools.gcp_tools import get_tools as gcp; print(f'GCP: {len(gcp())} tools OK')
"
```

Verify all handlers are callable and schemas present:
```bash
python -c "
from src.tools import aws_tools, kubernetes_tools, azure_tools, gcp_tools
for name, mod in [('AWS', aws_tools), ('K8s', kubernetes_tools), ('Azure', azure_tools), ('GCP', gcp_tools)]:
    tools = mod.get_tools()
    for t in tools:
        assert callable(t['handler']), f'{t[\"name\"]} handler not callable'
        assert 'input_schema' in t, f'{t[\"name\"]} missing schema'
    print(f'{name}: {len(tools)} tools verified')
"
```

### 2e. All Services (41 files)
```bash
python -c "
services = [
    ('chat_service', 'services.chat_service'),
    ('model_router', 'services.model_router'),
    ('model_failover', 'services.model_failover'),
    ('input_sanitizer', 'services.input_sanitizer'),
    ('credential_service', 'services.credential_service'),
    ('credential_encryption', 'services.credential_encryption'),
    ('infrastructure_sync', 'services.infrastructure_sync'),
    ('drift_detection', 'services.drift_detection'),
    ('ai_infrastructure', 'services.ai_infrastructure'),
    ('learning_sandbox', 'services.learning_sandbox'),
    ('notification_service', 'services.notification_service'),
    ('incident_response', 'services.incident_response'),
    ('root_cause_analyzer', 'services.root_cause_analyzer'),
    ('scheduler', 'services.scheduler'),
    ('webhook_handler', 'services.webhook_handler'),
    ('cost_explorer', 'services.cost_explorer'),
    ('performance_optimizer', 'services.performance_optimizer'),
    ('predictive_scaling', 'services.predictive_scaling'),
    ('security_scanner', 'services.security_scanner'),
    ('compliance_service', 'services.compliance_service'),
    ('audit_service', 'services.audit_service'),
    ('secret_detector', 'services.secret_detector'),
    ('rbac', 'services.rbac'),
    ('two_factor_service', 'services.two_factor_service'),
    ('api_gateway', 'services.api_gateway'),
    ('api_key_service', 'services.api_key_service'),
    ('chatops_service', 'services.chatops_service'),
    ('memory_service', 'services.memory_service'),
    ('stripe_integration', 'services.stripe_integration'),
    ('currency_detection', 'services.currency_detection'),
    ('multi_tenancy', 'services.multi_tenancy'),
    ('tier_enforcement', 'services.tier_enforcement'),
    ('terraform_service', 'services.terraform_service'),
    ('pdf_service', 'services.pdf_service'),
    ('email_service', 'services.email_service'),
    ('cache_service', 'services.cache_service'),
    ('secrets_manager', 'services.secrets_manager'),
    ('doctor', 'services.doctor'),
]
failed = []
for label, mod_path in services:
    try:
        __import__(mod_path)
        print(f'  {label}: OK')
    except Exception as e:
        failed.append((label, str(e)))
        print(f'  {label}: FAIL - {e}')
if failed:
    print(f'\n{len(failed)} service(s) failed to import')
else:
    print(f'\nAll {len(services)} services OK')
"
```

### 2f. All Route Blueprints (17 files)
```bash
python -c "
routes = [
    ('admin', 'routes.admin'),
    ('incidents', 'routes.incidents'),
    ('monitoring', 'routes.monitoring'),
    ('notifications', 'routes.notifications'),
    ('optimization', 'routes.optimization'),
    ('analysis', 'routes.analysis'),
    ('webhooks', 'routes.webhooks'),
    ('chatops', 'routes.chatops'),
    ('drift', 'routes.drift'),
    ('scaling', 'routes.scaling'),
    ('ai_infrastructure', 'routes.ai_infrastructure'),
    ('analytics', 'routes.analytics'),
    ('api_gateway', 'routes.api_gateway'),
    ('compliance', 'routes.compliance'),
    ('organizations', 'routes.organizations'),
    ('changes', 'routes.changes'),
]
failed = []
for label, mod_path in routes:
    try:
        __import__(mod_path)
        print(f'  {label}: OK')
    except Exception as e:
        failed.append((label, str(e)))
        print(f'  {label}: FAIL - {e}')
if failed:
    print(f'\n{len(failed)} route(s) failed to import')
else:
    print(f'\nAll {len(routes)} routes OK')
"
```

## Phase 3: App Startup Test

Start the app and verify it boots without errors:
```bash
cd C:\Users\shitt\Downloads\devops-agent
python app.py &
```

Wait ~8 seconds, then health check:
```bash
curl -s http://localhost:5000/health
```

Expected: `{"status":"healthy","agent_initialized":true,...}`

If startup fails, read the output for the traceback and fix immediately.

## Phase 4: Route Accessibility Test

With the app running, test that key pages return valid HTTP status codes (200 or 302 redirect to login for auth-protected routes):

```bash
# Public endpoints (should return 200)
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/health
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/login
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/signup

# Auth-protected endpoints (should return 302 redirect to /login)
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/chat
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/dashboard
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/settings
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/billing
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/monitoring
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/incidents
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/optimization
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/analysis
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/drift
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/scaling
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/ai_infrastructure
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/analytics
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/api_gateway
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/compliance
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/organizations
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/admin
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/chatops
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/webhooks
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/changes
```

Any 500 error = broken route. Investigate and fix immediately by:
1. Reading the app output log for the traceback
2. Identifying the broken template, missing method, or bad import
3. Fixing the code
4. Restarting the app and re-testing

## Phase 5: Template Rendering Validation

Check that all templates referenced by routes actually exist:

```bash
# List all templates referenced in route files and app.py
grep -rn "render_template" routes/ app.py | grep -oP "render_template\(['\"]([^'\"]+)" | sort -u
```

Cross-reference against actual template files:
```bash
find templates/ -name "*.html" | sort
```

Any template referenced but missing = will cause a 500 error. Create the missing template immediately.

## Phase 6: Database Schema Validation

Check that all model columns exist in the actual database:
```bash
python -c "
from app import app
from models import db
import sqlalchemy as sa

with app.app_context():
    inspector = sa.inspect(db.engine)
    tables = inspector.get_table_names()
    print(f'Tables in DB: {len(tables)}')
    for table in sorted(tables):
        cols = [c['name'] for c in inspector.get_columns(table)]
        print(f'  {table}: {len(cols)} columns')
"
```

If any model has columns not in the database, the auto-migration at startup should have added them. If not, investigate and fix.

## Phase 7: Test Suite

Run the full pytest suite:
```bash
python -m pytest tests/ -v --tb=short
```

Any failures must be fixed immediately:
1. Read the failure traceback
2. Identify root cause (broken import, schema mismatch, missing fixture, logic error)
3. Fix the code
4. Re-run the failing test to confirm

## Phase 8: Safety & Security Checks

### 8a. Verify all delete/update tools are classified in safety.py
```bash
python -c "
from src.tools import aws_tools, kubernetes_tools, azure_tools, gcp_tools
from src.agent.safety import SafetyValidator

sv = SafetyValidator()
high = sv.high_risk_tools
medium = sv.medium_risk_tools

unclassified = []
for name, mod in [('AWS', aws_tools), ('K8s', kubernetes_tools), ('Azure', azure_tools), ('GCP', gcp_tools)]:
    for t in mod.get_tools():
        tname = t['name']
        if ('delete' in tname or 'terminate' in tname or 'remove' in tname) and tname not in high:
            unclassified.append(('HIGH', tname))
        elif ('update' in tname or 'restart' in tname or 'modify' in tname) and tname not in medium and tname not in high:
            unclassified.append(('MEDIUM', tname))

if unclassified:
    print(f'{len(unclassified)} tools missing safety classification:')
    for level, name in unclassified:
        print(f'  {level}: {name}')
else:
    print('All destructive/update tools properly classified')
"
```

Any unclassified tools must be added to the appropriate list in `src/agent/safety.py`.

### 8b. Verify disabled billing endpoints
```bash
curl -s -X POST http://localhost:5000/api/subscription/upgrade | python -m json.tool
curl -s -X POST http://localhost:5000/api/credits/purchase | python -m json.tool
```
Both should return 403 (not 200).

## Phase 9: Service Wiring Check

Verify critical services are initialized and connected:
```bash
python -c "
from app import app, monitoring_service, incident_engine, notification_service, root_cause_analyzer
with app.app_context():
    print(f'Monitoring service: {type(monitoring_service).__name__}')
    print(f'Incident engine: {type(incident_engine).__name__}')
    print(f'Notification service: {type(notification_service).__name__}')
    print(f'Root cause analyzer: {type(root_cause_analyzer).__name__}')
    print('All critical services wired up')
"
```

## Phase 10: Remediation Report

After all phases, produce a summary:

| Phase | Status | Issues Found | Fixed |
|-------|--------|-------------|-------|
| Imports | PASS/FAIL | count | count |
| Tool validation | PASS/FAIL | count | count |
| Services | PASS/FAIL | count | count |
| Routes | PASS/FAIL | count | count |
| App startup | PASS/FAIL | count | count |
| Route accessibility | PASS/FAIL | count | count |
| Templates | PASS/FAIL | count | count |
| Database schema | PASS/FAIL | count | count |
| Test suite | PASS/FAIL | count | count |
| Safety classification | PASS/FAIL | count | count |
| Billing security | PASS/FAIL | count | count |
| Service wiring | PASS/FAIL | count | count |

## Remediation Rules

When fixing errors, follow these rules strictly:
- **Import errors**: Fix the import path, add missing dependency, or create the missing module
- **Missing templates**: Create the template extending `base.html` with a minimal content block
- **Missing model columns**: The auto-migration should handle this; if not, add an `ALTER TABLE` in a migration script
- **Missing methods on services**: Add the method as a stub that returns sensible defaults
- **Safety misclassification**: Add the tool name to the correct set in `safety.py`
- **Broken routes**: Fix the handler — usually a wrong method name, bad template reference, or missing import
- **Test failures**: Fix the test or the underlying code, never delete or skip the test
- **Always re-verify after each fix** — run the specific check again to confirm the fix works
