# DevOps Agent - Claude Context

> This file provides persistent context for Claude Code sessions.\n> See [CLAUDE_RUNBOOK.md](CLAUDE_RUNBOOK.md) for historical fixes.\n> See [CLAUDE_BILLING.md](CLAUDE_BILLING.md) for billing details.

## Project Overview

**DevOps Agent** is a Flask-based web application that provides an AI-powered DevOps automation assistant. Users interact via chat to manage cloud infrastructure (AWS, Azure, GCP), Kubernetes clusters, and CI/CD pipelines.

## Tech Stack

- **Backend:** Flask + SQLAlchemy (PostgreSQL default via `DATABASE_URL`; SQLite in-memory for tests)
- **Frontend:** Jinja2 templates + vanilla JavaScript
- **AI:** Kimi K3 (default, free/starter) + Anthropic Claude (professional/business)
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

    conversation.py # ConversationManager - message handling + token-aware compaction
    tool_selection.py # Progressive tool loading (classify_tool, select_tool_definitions)
    guardrails.py   # GuardrailsService - Haiku harmlessness pre-screen
  tools/
    aws_tools.py         # 352 AWS tools (EC2, VPC, IAM, RDS, Lambda, ECS, EKS, S3, etc.)
    kubernetes_tools.py  # 76 K8s tools (pods, deployments, services, namespaces, etc.)
    azure_tools.py       # 38 Azure tools (VMs, storage, SQL, NSGs, containers, etc.)
    gcp_tools.py         # 42 GCP tools (Compute, GCS, Cloud SQL, GKE, Cloud Run, etc.)
    cicd_tools.py        # 36 CI/CD tools (Jenkins + GitHub Actions + GitLab)
    terraform_tools.py   # 26 Terraform tools (init, plan, apply, destroy, state, workspace, import)
    sonarqube_tools.py   # 12 SonarQube tools (projects, quality gates, issues, analysis)
    nexus_tools.py       # 12 Nexus tools (repositories, components, assets, users, cleanup)
    docker_tools.py      # 22 Docker tools (containers, images, volumes, networks, compose, prune)
    git_tools.py         # 47 Git operations (clone, branch, commit, push, pull, merge, rebase, tags, stash, search, etc.)
    monitoring_tools.py  # 12 Prometheus + Datadog + Grafana tools
    pentest_tools.py     # 12 Security audit/scan tools (require pentest_config.enabled=True)
    ansible_tools.py     # 13 Ansible tools (playbooks, adhoc, inventory, vault, galaxy)
    alerting_tools.py    # 16 PagerDuty + OpsGenie alerting tools
    verification_tools.py # 2 service-reachability probes (http_check, tcp_check) — always registered, in ALWAYS_TOOL_NAMES
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
  skills_engine.py         # Skills: frontmatter parsing, trigger matching, learned infra context
  starter_templates.py     # Curated public infrastructure templates (data only)
  starter_workflows.py     # Curated pre-built workflow templates + seed_workflow_templates()
routes/
  artifacts.py             # Chat artifact CRUD + markdown export
  skills.py                # Skills activate/deactivate/list/learned endpoints
skills/                    # Built-in skill *.md files (loaded at startup, cached in memory)
  aws_cost_optimization.md
  kubernetes_troubleshooting.md
  security_hardening.md
  incident_runbooks.md
  terraform_best_practices.md
templates/
  index.html               # Main chat UI (dark terminal aesthetic, centered nav, artifacts panel)
  settings/
    skills.html            # Skills toggle grid + learned infrastructure summary
```

## Tool Inventory (749 total, 18 modules)

> Counts verified by `'handler':` occurrences across `src/tools/*_tools.py`
> (`tests/test_tool_counts.py` guards this against the user-facing pages).
> Three modules below are not detailed in the per-provider sections:
> `command_tools` (2), `devops_operations_tools` (10), and `verification_tools`
> (2 — `http_check`, `tcp_check`).

### AWS (352 tools)
Full lifecycle management: EC2, VPC, IAM, RDS, Lambda, ECS, EKS, S3, DynamoDB, CloudFormation, Route53, SNS/SQS, SSM, CloudWatch, ElastiCache, EFS, EventBridge, Kinesis, NAT Gateway, Load Balancers, Target Groups, ECR, Secrets Manager, Service Quotas, Resource Groups.

**`find_ami` is the AMI-resolution step `create_ec2_instance` depends on.**
`create_ec2_instance` requires a concrete `ami_id` and cannot turn "ubuntu" into
one. Until 2026-09-02 nothing in the catalog could: the only AMI tools were
`create_ami` (images a running instance) and `deregister_ami`. A plain "create an
ec2 instance using ubuntu on a t2.micro" was therefore **unsatisfiable**, and the
model guessed — in production it called `list_iam_roles`, and on an earlier turn
`gcp_api_read`/`gcp_api_write`, against the user's real account (see
CLAUDE_RUNBOOK.md's 2026-09-02 entry). `find_ami` resolves distro + version to the
newest matching AMI and **pins the distribution vendor's own owner account**
(`_AMI_OWNERS`) — never match an AMI by name alone, since anyone can publish a
public image with a lookalike name. Add new distros to `_AMI_OWNERS` /
`_AMI_NAME_PATTERNS` together, and only with a verified owner id.
`distro='dlami-gpu'` (added 2026-10-12) resolves the AWS Deep Learning Base GPU
AMI on Ubuntu (`version` = Ubuntu release, e.g. `24.04`) — NVIDIA driver, Docker
and the NVIDIA container toolkit preinstalled, owner alias `amazon` per the AWS
DLAMI docs. It backs the AI/ML workflows below.

### Kubernetes (76 tools)
Pods (list, describe, logs, delete, exec), Deployments (list, describe, create, update image, delete), Services (list, create, delete), Namespaces (list, get, create, delete), ConfigMaps (create, delete), Secrets (create, delete), Ingress (create, delete), Nodes (list, cordon, uncordon), Jobs (create, delete).

**Which cluster a call reaches (`src/tools/k8s_access.py`, 2026-10-17).** On the hosted site the
tools reach the signed-in user's **EKS clusters through their connected AWS account**: describe the
cluster with their boto credentials, then sign a token ourselves (a presigned STS
`GetCallerIdentity` URL with the `x-k8s-aws-id` header, never the `aws` CLI, which would use the
server's own credentials). The server's kubeconfig is **never** read unless
`K8S_USE_LOCAL_KUBECONFIG=true` (self-hosted installs and the CLI). Before this, all 76 tools
called `config.load_kube_config()`: on the hosted site they either failed or would have handed every
user whatever cluster the server could reach, and the process-wide config could cross between
concurrent users.
- `context` is an EKS cluster name, `region/name` or ARN; blank works only when the account has
  exactly one cluster in its default region (otherwise the error lists them). `list_contexts`
  lists the user's clusters.
- Every call builds its own `ApiClient`; `_get_k8s_client()` returns CoreV1/AppsV1 bound to it and
  `_k8s_api_client()` gives it to other API groups. **Never** construct `client.XxxApi()` with no
  argument or call `load_kube_config` in this module (`tests/test_eks_cluster_access.py` fails).
- Refused: private-only endpoints, clusters not ACTIVE, an endpoint that isn't `*.eks.amazonaws.com`.
- The cluster must let the customer's DevOps Agent role in through an **EKS access entry**
  (`AmazonEKSViewPolicy` for read-only). A 401/403 result gets a `hint` naming the role ARN and the
  `create_eks_access_entry` / `associate_eks_access_policy` calls (`_with_access_hint` in `get_tools()`).
- Tokens and endpoints are cached 10 minutes per (user, region, cluster). GKE, AKS, other clusters
  and private EKS endpoints are not supported yet (scoped 2026-10-17: saved token connections next,
  an in-cluster agent only if asked for).

### Azure (38 tools)
VMs (list, describe, start, stop, restart, create, delete), Storage (list accounts, create, delete, list keys, regenerate key), SQL (list servers, create server, delete server, delete database, firewall rules), NSGs (list, create, create rule, delete), Container Instances (list, create, delete, restart), Disks (list, create, delete), VNets (list, create), Public IPs (list, delete).

### GCP (42 tools)
Compute (list, describe, start, stop, create, delete, snapshots), GCS (list buckets, create, delete, list objects), Cloud SQL (list, create, delete, restart), GKE (list clusters, describe, resize, delete), Cloud Run (list, deploy, delete), Pub/Sub (list topics, create topic, delete topic, create subscription), Secret Manager (list, create, delete, add version), BigQuery (list datasets, create, delete), Firewall (list, create, delete), Cloud Functions (list, delete), Cloud Logs.

### CI/CD — Jenkins + GitHub Actions + GitLab (36 tools)
`trigger_jenkins_job`, `get_jenkins_job_status`, `get_jenkins_build_logs`, `list_jenkins_jobs`, `get_jenkins_queue`, `abort_jenkins_build`, `enable_jenkins_job`, `disable_jenkins_job`, `get_jenkins_job_config`, `list_jenkins_nodes`, `delete_jenkins_build`.
Credentials: the user's Jenkins connection (Settings > Integrations) or explicit params; never env vars.

### CI/CD — GitHub Actions (10 tools)
`trigger_github_workflow`, `get_github_workflow_runs`, `list_github_workflows`, `get_github_workflow_run`, `cancel_github_workflow_run`, `rerun_failed_github_jobs`, `list_github_runners`, `list_github_secrets`, `list_github_environments`, `get_github_workflow_usage`.
Plus `get_github_run_jobs` (jobs, failed steps, failed-job log tails).
Credentials: the user's GitHub connection or an explicit `github_token`; never env vars.

### Terraform (26 tools)
`terraform_init`, `terraform_plan`, `terraform_apply`, `terraform_destroy`, `terraform_show`, `terraform_output`, `terraform_validate`, `terraform_fmt`, `terraform_workspace_list`, `terraform_workspace_select`, `terraform_workspace_new`, `terraform_state_list`, `terraform_import`, `terraform_state_move`, `terraform_state_rm`, `terraform_refresh`.
All tools take `working_dir` as the primary param.

### SonarQube (12 tools)
`get_sonar_projects`, `get_sonar_project_quality`, `get_sonar_measures`, `get_sonar_issues`, `trigger_sonar_analysis`, `get_sonar_hotspots`, `create_sonar_project`, `delete_sonar_project`, `update_sonar_issue`, `list_sonar_quality_gates`, `assign_sonar_quality_gate`, `get_sonar_analysis_history`.
Credentials: the user's SonarQube connection (or explicit `token`) + `base_url`, which must match the saved server's origin.

### Nexus Repository Manager (12 tools)
`nexus_get_system_status`, `nexus_list_repositories`, `nexus_get_repository`, `nexus_create_repository`, `nexus_delete_repository`, `nexus_search_components`, `nexus_get_component`, `nexus_delete_component`, `nexus_list_assets`, `nexus_delete_asset`, `nexus_list_users`, `nexus_run_cleanup_task`.
Credentials: the user's Nexus connection (or explicit username/password) + `base_url`, which must match the saved server's origin.

### Docker (22 tools)
`docker_list_containers`, `docker_get_container_details`, `docker_manage_container`, `docker_get_container_logs`, `docker_list_images`, `docker_pull_image`, `docker_remove_image`, `docker_list_volumes`, `docker_list_networks`, `docker_get_stats`, `docker_compose_up`, `docker_compose_down`, `docker_build_image`, `docker_create_container`, `docker_create_network`, `docker_remove_network`, `docker_create_volume`, `docker_remove_volume`, `docker_exec`, `docker_tag_image`, `docker_push_image`, `docker_system_prune`.
Requires Docker daemon running locally (uses `docker.from_env()`).

### Other modules
- **Git (47)**: repository setup (clone, init, remotes), inspection (show, blame, log, file-at-commit), branching (create, switch, delete, merge, rename), staging & committing (add, commit, reset, amend), remote ops (fetch, pull, push, force-push, cherry-pick), tags (list, create, delete, push), stashing (save, list, apply, drop), search (grep, commit search, shortlog), maintenance (clean, revert, rebase, reflog, count-objects, diff-stat)
- **GitHub (19)**: repos (list, get, create, delete), issues (list, create, close), PRs (create, merge, close), branches (list, create), releases (list, create), workflows (list, runs, trigger), collaborators (list, invite)
- **Monitoring (12)**: Prometheus, Datadog, Grafana
- **Pentest (12)**: nmap, nikto, sqlmap, ZAP, cloud security audits — require
  `pentest.enabled=true`, which **defaults to false** since 2026-09-02. Enabling it registers
  all 12 into every user's catalog, where they compete for tool selection: that is how
  `nmap_port_scan` became reachable from an EC2 request. Set `PENTEST_ALLOWED_TARGETS` too.
- **Ansible (13)**: playbook run, ad-hoc, inventory, vault, galaxy
- **Alerting (16)**: PagerDuty + OpsGenie incidents/alerts

## Non-negotiable: every feature runs against a real cloud account

**No feature may work in isolation.** Every feature in this app operates on the user's
attached cloud account (AWS, Azure, or GCP). A feature must never produce results from
hardcoded, sample, or simulated data when no cloud account is connected — if there is no
account, it says so and does nothing. This applies to anything built here, not just tools:
dashboards, reports, scans, recommendations, drift, cost, compliance.

**Why this is stated as a rule:** canned output is indistinguishable from a real query, so
the user acts on fiction. Found live 2026-08-12 — `DriftDetectionService._get_actual_state()`
returned hardcoded dicts under a `# In a real implementation, this would call AWS APIs`
comment, with no RDS branch at all, while `/api/import/sample` seeded fake baselines
(`i-0abc123def456`, `sg-12345`, `production-database`). Every user got a byte-identical
report, including a **critical** "security group open to `0.0.0.0/0`" alert that was a
literal in the source, against an account with no database in it. See CLAUDE_RUNBOOK.md.

**This has recurred beyond Drift.** A 2026-09-02 scheduled audit found the entire Predictive
Scaling feature (`/scaling`, `services/predictive_scaling.py`; removed 2026-10-14) unconditionally fabricating three
named resources and their metric history for every user with no `[Sandbox]` label, plus an "Apply"
endpoint that reported fake `status: 'applied'` success without calling any cloud API — fixed (see
CLAUDE_RUNBOOK.md's 2026-09-02 entry). The same audit found `services/analytics_service.py`'s
"Advanced Analytics Dashboard" (`/analytics/*`) doing the identical thing at larger scope —
hardcoded per-service/per-team cost breakdowns, a cost *forecast* built on `random.uniform()` noise
— flagged at the time, not yet fixed. **Fixed by the 2026-09-19 scheduled audit**: every metric now
sources from the user's real AWS Cost Explorer/CloudWatch data (`services/cost_explorer.py`,
already used elsewhere in the app) or this app's own per-user tables (`InfrastructureResource`,
`IncidentModel`, `UsageLog`), falling back to honest zeros/empty series — never invented numbers.
See CLAUDE_RUNBOOK.md's 2026-09-19 entry for the full before/after and what's still an approximation
(deployment stats are derived from CI/CD tool call history, since this app has no dedicated
Deployment model). If a new feature's data
doesn't visibly come from `credential_service`/a provider tool/a real DB query, assume it's the
same bug until traced.

**Three more instances found by the 2026-09-15 scheduled audit.**
`services/chatops_service.py`'s `_cmd_metrics`/`_cmd_oncall` delivered a hardcoded metrics block
and on-call roster into Slack as if live — **fixed by the 2026-09-13 scheduled audit** (see
CLAUDE_RUNBOOK.md's 2026-09-13 entry; it predates the 2026-09-15 audit that re-flagged it, so
that entry was already stale when written). `services/performance_optimizer.py`'s
`_generate_sample_recommendations()` seeded the literal `i-0abc123def456` fake instance id (the
same id from the 2026-08-12 drift incident above) plus four other hardcoded resources
(`prod-db`, `default/api-service`, `vol-0xyz789`, `data-archive`) for every user with no cloud
account, rendered at `/optimization/` and `/optimization/recommendations` — **fixed by the
2026-09-20 scheduled audit** (the whole Optimize area was later removed, 2026-10-13): `_get_user_recommendations()` now returns an empty dict until a
real caller feeds it live resource data via the existing (previously unused)
`analyze_resource()` entry point, same fail-closed shape as `predictive_scaling.py`'s fix. The
same audit found the identical fake-Apply shape one call site over: `app.py`'s
`/api/dashboard/recommendations/<id>/apply` (backing the "Apply" button on `dashboard_live.html`,
operating on the real, CloudWatch-derived `CostOptimization` rows from
`services/infrastructure_sync.py`) set `status='applied'` and returned a success toast
("Optimization applied — saving $X/mo") without calling any cloud API to stop/resize/reconfigure
anything — fixed the same way `routes/scaling.py`'s `api_apply_recommendation` was: an honest
501 `not_implemented` response, never a fabricated `applied` status. **Fixed by the 2026-09-21
scheduled audit:** `services/ai_infrastructure.py`'s `get_recommendations()` had the identical
hardcoded-list-ignoring-`user_id` shape (four fake recommendations, `rec_1`..`rec_4`, including an
invented "$150/mo savings" figure) and its `apply_recommendation()` reported `success: True` with
no cloud API call — fixed the same fail-closed way as every instance above (`get_recommendations`
now returns `[]`, `apply_recommendation` always returns the same "not yet implemented" 501 shape).
See CLAUDE_RUNBOOK.md's 2026-09-15, 2026-09-20, and 2026-09-21 entries for exact line numbers.
This was the eighth known instance of the same bug class (Drift, Predictive Scaling, Analytics,
ChatOps, Performance Optimizer, the dashboard cost-recommendation Apply endpoint,
`routes/scaling.py`'s Apply endpoint, and AI Infrastructure) found independently across seven
separate audits — the recurrence itself, not just any one instance, is the signal that this needs
a structural fix (e.g. a shared "no live account → fail closed" helper every new
recommendation/analytics feature is required to call, and a shared "apply" helper that refuses to
report success without an actual tool call) rather than another one-off patch next time a ninth
instance is found.

**When building or reviewing a feature:**
- Trace where its data comes from. If the answer is a literal in the source, it isn't done
  — however finished the UI looks.
- Tells to grep for: `# For now`, `# In a real implementation`, `simulated`, `sample_`,
  hardcoded `i-0…` / `sg-…` / `vpc-…` ids.
- Read live state through the per-user credential path
  (`services/credential_service.get_user_boto_client(user_id, …)`, `aws_tools._get_boto_client()`,
  or the Azure/GCP equivalents) — never ambient app credentials, never a stub.
- No credentials → fail closed with "connect a cloud account". Never fall back to demo data.
- **Distinguish "cannot read the account" from a finding.** They are opposite conclusions,
  and reporting the first as the second is exactly how fabricated findings ship. Drift uses
  `DriftScanError` for this; new features need an equivalent.
- The only exception is sandbox mode (`UserPreferences.sandbox_mode`), which is explicit,
  user-enabled, and labelled `[Sandbox]`. It is not a substitute for a missing account.

## Critical Security Patterns

### User Isolation (NEVER bypass)
- ALL database queries MUST filter by `user_id=current_user.id`
- Conversations, messages, credentials are per-user
- Cloud operations use per-user encrypted credentials
- **A service class constructed with a `user_id` must apply it on every read, not just writes.**
  `services/compliance_service.py` (removed 2026-10-14)'s `ComplianceService.__init__` always stores `self.user_id`
  (every real call site — `routes/compliance.py`, `app.py`, `tasks/security_tasks.py` — passes a
  real one), but `get_policy()`/`get_compliance_report()` did a bare `Model.query.get(id)` with no
  `user_id` filter, so `toggle_policy`/`delete_policy`/`update_policy`/`get_report`/`export_report`
  (all of which call one of those two getters) let any logged-in user toggle, delete, or download
  another user's compliance policy/report by guessing the integer id. Fixed by filtering both
  getters on `self.user_id` when set — see CLAUDE_RUNBOOK.md's 2026-07-27 scheduled-audit entry.
  When adding a new per-user service class, an instance-level `user_id` is only a security
  boundary if every getter actually filters by it — storing it on `self` isn't enough on its own.
  A third getter on the same class, `get_framework()`, was missed by that fix and had the
  identical unfiltered `Model.query.get(id)` shape — reachable via `routes/compliance.py`'s
  `framework_detail`/`enable_framework` (both only `@login_required`, no ownership check of their
  own), letting any user read another user's compliance framework by guessing the id. Fixed the
  same way (filter on `self.user_id` when set) — see CLAUDE_RUNBOOK.md's 2026-08-01 entry. A
  service class with a security-relevant `user_id` needs *every* getter audited when the class is
  touched again, not just the ones a bug report happens to point at.
- **A non-Flask-session entry point (a bot, webhook, or CLI) that calls a per-user service still
  needs a real app `user_id` from somewhere — it doesn't get one for free.** (ChatOps itself was
  removed 2026-10-14; the lesson stands for any future bot or webhook entry point.) Every method on
  `IncidentResponseEngine`/`RootCauseAnalyzer`/`ProactiveMonitoringService` (all since removed) required `user_id` as
  its first positional arg, same as any other per-user service in this app. `services/chatops_service.py`
  (Slack/Teams bot commands) called all of them with no `user_id` at all, or with the Slack-typed
  incident-id string landing in the `user_id` slot, because there was no mechanism to map a
  Slack/Teams identity to an app `User.id` in the first place — found by the 2026-09-12 scheduled
  audit (see CLAUDE_RUNBOOK.md). Fixed with a `ChatOpsIdentity` (platform + platform_user_id →
  user_id) mapping, populated via a `/link <code>` command that redeems a short-lived
  `ChatOpsLinkCode` generated on the logged-in ChatOps page; `ChatOpsService.process_message()`
  resolves and injects `app_user_id` before dispatch, refusing to dispatch a `requires_auth`
  command with no resolved identity rather than calling the handler with nothing valid to pass.
  Any new ChatOps command that touches per-user data must accept `app_user_id` from `process_message`'s
  dispatch, never invent its own notion of "the user" from the raw platform id.
  Since 2026-10-13 `process_message()` also refuses a `requires_auth` command with no resolved
  identity *before* dispatch, so a handler that forgets `_require_app_user()` (as
  `_cmd_deployments` once did) still fails closed.
  History: until then `ChatCommand.requires_auth` was declarative only and enforcement was
  per-handler discipline. The 2026-09-24 scheduled audit found `_cmd_deployments` never called
  `_require_app_user()` and served `WebhookEventRecord` (a platform-wide table with no `user_id`,
  `@admin_required` everywhere else it's read) to any Slack/Teams user, linked or not. It is now
  gated on a resolved app user plus `services.rbac.user_is_admin()` (see CLAUDE_RUNBOOK.md's
  2026-09-24 entry), and the central dispatch check above backstops any future handler that
  forgets; `tests/test_chatops_deployments_access_control.py` registers such a handler to prove it.
- **A route rendering another entity's nested child (team, resource, sub-object) must check the
  parent-membership guard itself — checking the child's `parent_id` foreign key is not the same
  as checking access.** `routes/organizations.py`'s `view_team` fetched `membership =
  service.get_membership(org_id, current_user.id)` and passed it to the template, but never
  checked it was non-`None` before rendering — unlike every sibling route in the file
  (`list_teams`, `list_members`, `view_organization`), which all `if not membership: redirect`.
  It only validated `team.organization_id == org_id`, so any logged-in user (not just a
  non-member) could view any organization's team roster by URL-guessing `org_id`/`team_id`. Fixed
  by adding the same membership guard used elsewhere in the file — see CLAUDE_RUNBOOK.md's
  2026-08-01 entry.

### Credential Storage
- `UserCloudCredential` model stores encrypted credentials
- Uses Fernet (AES-128) encryption via `credential_encryption.py`
- Key derived from `CREDENTIAL_ENCRYPTION_KEY` or `SECRET_KEY`
- **AWS dual-mode auth** (`credential_service.py`):
  - `auth_mode='access_key'`: Direct IAM access key + secret key (simple, for self-hosting teams)
  - `auth_mode='role_arn'`: IAM Role ARN + optional External ID → STS AssumeRole for temp creds (enterprise, cross-account)
  - `get_user_boto_client()` / `get_user_boto_resource()` handle both modes transparently
  - Settings UI (`templates/settings.html`) and onboarding wizard (`templates/onboarding.html`) both have a mode toggle; **role ARN is the recommended default** (access keys demoted to fallback for self-hosted setups)
  - Trust policy instructions in both UIs render the platform account ID from `PLATFORM_AWS_ACCOUNT_ID` env var (default `188046727805`), exposed via the `/settings` and `/onboarding` routes in `app.py`; the quick-create template link comes from `CF_TEMPLATE_URL` (same routes). The two must move together — the template's trust policy names that account.
  - **Migration bridge** (`PLATFORM_BRIDGE_ROLE_ARN`, unset by default): when a direct `AssumeRole` into a customer role is **denied**, `_assume_role()` retries by first assuming that bridge role in the *previous* platform account and chaining from it (External ID still sent; chained sessions max 3600s). Exists only so role-based customers keep working while they update trust policies after a platform account move — each bridged call logs `assumed via migration bridge`. Unset it once that log goes quiet. Full procedure: `docs/aws-account-migration.md`; `scripts/count_role_arn_customers.py` lists who is affected (and reports undecryptable credentials, a check that the encryption key carried over).
  - **AWS access levels (2026-10-15, owner decision).** The CloudFormation `PolicyLevel` is
    `Read` (default) / `Manage` / `ReadOnly` / `Management`. **Read** = AWS-managed
    `ViewOnlyAccess` + `SecurityAudit` + the published read-only policy; **Manage** =
    `PowerUserAccess` + the published management policy. Every level also gets the
    `DevOpsAgentGuardrails` inline deny: secret values always, and on Read the data reads
    (`DATA_READ_ACTIONS` in `scripts/build_cf_template.py`), so "metadata, not data" holds
    whatever AWS puts in its managed policies. Why: the hand-picked list of ~45 services left
    out GuardDuty and every other unlisted service, so the agent was refused and had to ask
    for each permission. `ReadOnly`/`Management` are the old lists, kept as "Strict" and so
    existing stacks (which update with `UsePreviousValue`) never get broader access without
    choosing it. Settings and onboarding pass the choice as `param_PolicyLevel`; Azure
    (Reader/Contributor) and GCP (Viewer/Editor) already used built-in roles. Guarded by
    `tests/test_iam_policies.py`. **Re-upload the template to S3 after merging.**
  - **Published least-privilege IAM policies** (`static/iam/devops-agent-readonly.json` + `devops-agent-management.json`, docs in `docs/iam-policies.md`): read-only = metadata never data (no `s3:GetObject`, `secretsmanager:GetSecretValue`, `ssm:GetParameter`, `lambda:GetFunction`); management = service writes but IAM read-only + `iam:PassRole` conditioned to AWS service principals, secret values still excluded. Guarded by `tests/test_iam_policies.py` — update the tests if you change the policy guarantees.
  - **CloudFormation quick-create**: `cloudformation/devops-agent-role.json` is generated from the policy files by `scripts/build_cf_template.py` and hosted at `s3://devopsagent-cf-templates/devops-agent-role.json` (public read — quick-create requires an S3 URL). "Create role with CloudFormation" buttons in settings + onboarding auto-generate an External ID and open the console quick-create page. **After editing a policy file: re-run the build script and re-upload to S3** (command in `docs/iam-policies.md`); a sync test fails if the committed template drifts.
  - **Public `/security` trust page** (`templates/security.html`, route `security_page` in `app.py`): credential handling, auditable policy links, sandbox pitch, guardrails stack, vulnerability contact (`security@devopsagent.io`). Linked from landing + about footers. Onboarding step 1 has a "Start in sandbox" callout that PUTs `{sandbox_mode: true}` to `/api/preferences` and completes onboarding without credentials.

### Authentication
- `@login_required` decorator on all API routes
- Email verification required for new accounts
- Account lockout after 5 failed attempts
- **Email lookups are case-insensitive everywhere** (`/login` matches `func.lower(User.email)`; every other entry point lowercases input). A case-sensitive email match rejects phone logins, because mobile keyboards auto-capitalize the first letter. Usernames are exact-match.
- `routes/auth.py`'s `login()` always runs a bcrypt comparison before returning, even for an
  unknown email/username — `_run_timing_safe_password_check()` checks against a fixed dummy hash
  (`_DUMMY_PASSWORD_HASH`) when no account is found, so response time can't be used to enumerate
  valid accounts (bcrypt's cost, not the identical error text, was the actual signal). Any new
  early-return added before the password check in this route reopens that timing side channel —
  route it through `_run_timing_safe_password_check()` instead of `user.check_password()` directly.
  `routes/mcp.py`'s MCP OAuth `oauth_authorize()` POST handler reimplemented its own
  `if not user or not user.check_password(password)` check (independent login form for the MCP
  connector flow) and reopened the same side channel — fixed by importing and routing through
  `routes.auth._run_timing_safe_password_check()` there too. Any other route that authenticates a
  user with a password must use this helper, not a direct `check_password()` call. That same
  `oauth_authorize()` fix left a second gap standing: it never called `User.is_locked()` /
  `record_failed_login()`, so the account-lockout invariant on this line was enforced only on
  `/login` — a known email could be brute-forced through `/mcp/oauth/authorize` (and its
  `/authorize` alias) with no per-account limit at all, no matter how many failed attempts
  `/login` itself would have already blocked. Found by the 2026-09-18 scheduled audit and fixed by
  wiring in the same `is_locked`/`record_failed_login`/`update_last_login` calls `/login` uses,
  plus a `@limiter.limit("10 per minute")` matching `/login`'s own rate limit (the route previously
  had none of its own, only the blueprint-wide default of 100/hour per IP). **A route that
  reimplements password verification instead of calling a shared login helper must also
  reimplement every invariant that helper enforces, not just the timing-safety one that happened
  to already have a name and a runbook entry** — the same lesson as the guardrails-pipeline
  duplication problem elsewhere in this file, just for authentication instead of jailbreak
  screening.
  That lesson recurred on 2026-10-13: `oauth_authorize()` also skipped **2FA and SSO
  enforcement**, so a password alone connected Claude to a 2FA account. It now shows a code step
  before any auth code is issued. The step's token is signed with itsdangerous, lasts 10 minutes
  and is bound to the client_id, redirect_uri and PKCE challenge. It shares `routes/auth.py`'s
  `_check_mfa_code`, `_register_failed_mfa` (one attempt counter and lockout), `_send_email_otp`
  and `_migrate_sms_mfa`, and SSO-enforced accounts are refused there as on `/login`. Pinned by
  `tests/test_mcp_oauth_2fa.py`.
- `forgot_password()` dispatches token generation, persistence, and the password-reset email send
  through `_dispatch_password_reset_email()` on a background daemon thread, rather than doing that
  work inline before responding — an existing account's token write + synchronous outbound email
  API call (up to a 10s timeout) is a much larger and more network-variable timing signal than
  login's bcrypt cost would have been, and both branches already render the identical generic
  success message. **Any route that conditionally does slow work (DB write, outbound API/email
  call) only when a resource/account exists is a timing side channel** even if the response text
  never reveals which branch ran — dispatch the slow part asynchronously (same pattern as
  `services/notification_service.py`'s async Slack dispatch: re-enter the app context and re-query
  by id inside the thread, never pass a live ORM object across the thread boundary) so response
  time stays uniform.

### CSRF enforcement (`app.py`'s `_enforce_csrf_on_form_submissions`)

`CSRFProtect(app)` is initialized but `WTF_CSRF_CHECK_DEFAULT` is **`False`**, so Flask-WTF's
automatic per-request check is off. That is deliberate — the JSON surfaces (`/api/*`, the MCP
transport, the developer REST gateway, the HMAC-signed inbound webhook receiver) send no CSRF
token and would break under a blanket check. **Disabling it was only ever half a design**: the
other half, per-endpoint `@csrf.protect`, was never written. Four auth routes — `/login`,
`/signup`, `/forgot-password`, `/reset-password` — do validate by hand through `routes/auth.py`'s
`_check_csrf()`, and **those four were the only form endpoints ever checked**. Every other
form-encoded POST (`/profile`, the organization create/invite/settings forms, compliance policy
and evidence, API key and webhook creation) rendered no token and validated none. The four
`_check_csrf()` calls are deliberately kept: the hook preempts them, but their inline error
message is the only feedback those pages can give, since none of the four auth templates render
flash messages. See CLAUDE_RUNBOOK.md's 2026-09-19 entry.

The enforcement now lives in a single `@app.before_request` hook, `_enforce_csrf_on_form_submissions()`:

- **It gates on MIME type, not on route.** Only `application/x-www-form-urlencoded` and
  `multipart/form-data` (`_CSRF_FORM_MIMETYPES`) are checked. This is the actual security
  boundary, not a convenience: those two are CORS "simple requests" that any cross-origin page
  can send with the victim's cookies attached, whereas a cross-origin page cannot send
  `Content-Type: application/json` without a preflight it has no way to satisfy. **A new JSON
  endpoint needs no exemption; a new form endpoint is covered automatically.**
- **It mirrors Flask-WTF's own `csrf_protect` hook** — it reads that extension's private
  `csrf._exempt_blueprints` / `csrf._exempt_views` sets so existing `csrf.exempt(...)` calls keep
  working. That is why `flask-wtf` must stay `==`-pinned (see the Dependency Pinning Policy);
  **re-verify this hook against `flask_wtf/csrf.py` if that pin moves.**
- **A rejection is a 303 redirect, not a 400.** `handle_csrf_error` flashes "Your session
  expired…" and bounces the browser back — a failure here is far more often a stale session than
  a real forgery. The referrer is validated through `routes.auth._is_safe_redirect()` before being
  used as the target: on a genuinely forged request the referrer points at the attacker's page,
  and redirecting there would make the error handler itself an open redirect.
- Guarded by `tests/test_csrf_enforcement.py` (8 tests). The 303 is the discriminator the tests
  key on — no ordinary `/login` outcome returns it (bad password re-renders 200, success is 302).
  **A regression here is silent** (forms keep working, they just stop being checked), so both
  halves are asserted: form-without-token rejected *and* JSON-without-token not blocked.

**When adding a form-rendering template, it must include
`<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`** — the hook will otherwise
reject the submission at runtime with no compile-time warning.
Check **each `<form>`** individually, not the template as a whole: `verify_2fa.html` had a token in its secondary form but not in its main code form, and that locked every 2FA user out until 2026-10-02 (see CLAUDE_RUNBOOK.md).

### Guardrails (Jailbreak / Prompt Injection Defense)
Three-layer stack applied at `/api/chat`, `/api/chat/stream`, and the developer REST API
(`/v1/agent`, `/v1/agent/stream` in `routes/api_gateway.py`) before any credit is deducted:

1. **`validate_message()`** (`services/input_sanitizer.py`) — blocks messages with injection patterns (10 regex rules) and enforces a 10,000-char limit. Returns `(bool, reason)`.
2. **`screen_message()`** (`src/agent/guardrails.py`) — Haiku pre-screen using structured tool output. Classifies: `prompt_injection`, `out_of_scope_attack`, `malware_request`, `data_exfiltration`, `social_engineering`. Also runs crisis-language detection (fails closed) before the Haiku call. Fails open on error.
3. **Hardened system prompt** (`src/agent/core.py`) — `SECURITY BOUNDARIES` section: fixed identity, no prompt disclosure, refuse malware generation, reject in-message operator impersonation.

**Every guardrail-gated route MUST, in order:** `sanitize_input()` the raw message → check `current_user.is_guardrail_blocked()` (or the equivalent `User` row for API-key routes) → `validate_message()` → `screen_message()`, calling `record_guardrail_violation()` on any block. Skipping `screen_message()`/`sanitize_input()` on a new entry point (as `routes/api_gateway.py`'s developer API originally did, `api/v1/conversations.py`'s `send_message()`/`api_v1_chat_stream()` did later, and `routes/curriculum.py`'s `/curriculum/api/ai-guide` did after that — all now fixed) silently drops the Haiku jailbreak screen, crisis detection, and lockout enforcement for that surface — see `CLAUDE_RUNBOOK.md`. Compliant chat-to-agent entry points today: `app.py` (`/api/chat`, `/api/chat/stream`), `routes/api_gateway.py` (`/v1/agent`, `/v1/agent/stream`), `api/v1/conversations.py` (`/conversations/<id>/messages`, `/chat/stream`), and `routes/curriculum.py` (`/curriculum/api/ai-guide`).

**Not yet fixed, flagged by the 2026-08-26 scheduled audit:** this 4-step pipeline is still hand-copied at all 8 call sites above (2 in `app.py`, 2 in `routes/api_gateway.py`, 2 in `api/v1/conversations.py`, 1 in `routes/curriculum.py`, plus the block itself in `routes/curriculum.py`) — despite three separate past incidents of a *new* entry point missing the pipeline, there is still no single `enforce_guardrails(user, message)` helper in `src/agent/guardrails.py` that all 8 sites call. Each copy has to be kept in sync by hand, which is exactly the shape that caused the three prior misses. Extracting a shared helper is the structural fix; not done in this pass because it touches all 8 guardrail-critical call sites at once and warrants its own reviewed change rather than a drive-by edit during a read-mostly audit.

**Violation tracking on `User` model:**
- `guardrail_violations` (Integer) + `guardrail_blocked_until` (DateTime)
- `record_guardrail_violation()` — increments counter; blocks for 1 hour after 3 violations
- `is_guardrail_blocked()` — auto-unblocks and resets counter after block expires
- Run `migrate_missing_columns.py` to add these columns to existing databases

### Secret redaction on chat/agent response paths (`services/secret_detector.py`)

The backstop for `get_secret_value`/`create_ec2_keypair`-class tools (both classified high-risk in
`safety.py` specifically because they disclose live secret plaintext into the response path):
`redact_secrets(text)` scans a whole string against `SECRET_PATTERNS` (AWS/Anthropic/OpenAI/Stripe/
GitHub keys, bearer tokens, private key blocks, DB connection strings, Slack/Discord webhooks, etc.)
and replaces matches with `[REDACTED]`. **Every chat-to-agent response surface must redact before
persisting to `ChatMessage` and before returning/streaming to the caller** — found missing entirely
on 3 of the 4 documented guardrail-gated entry points (`routes/api_gateway.py`'s `/v1/agent`+
`/v1/agent/stream`, `api/v1/conversations.py`'s `send_message()`+`api_v1_chat_stream()`) by the
2026-09-14 scheduled audit; only `app.py`'s `/api/chat`+`/api/chat/stream` had it, and even there
with a chunk-boundary gap (see below). All fixed the same day — see CLAUDE_RUNBOOK.md.

**A streaming response cannot just call `redact_secrets(chunk)` per chunk.** Anthropic's raw
`content_block_delta` events are often just a handful of characters, so a real 20+ char secret has a
high chance of landing split across two or more chunks and matching nothing per-chunk, even though
the final assembled string is redacted correctly before it's saved to the DB — the persisted history
looks clean while the raw secret already reached the browser during streaming. Use
`StreamingRedactor` (same module) instead: `feed(chunk)` holds back a trailing window of unredacted
text (long enough for any `SECRET_PATTERNS` match, and never cuts through a match still forming at
the boundary) and returns only the portion now safe to emit; call `flush()` once at stream end for
whatever's left buffered. Wired into all 3 streaming loops (`app.py`, `routes/api_gateway.py`,
`api/v1/conversations.py`); the Kimi streaming path buffers its whole response before yielding for
unrelated hallucination-check reasons and was never affected. `routes/curriculum.py`'s
`/curriculum/api/ai-guide` is a plain curriculum Q&A completion with no tool execution, so it has no
path to disclose a live cloud secret and doesn't need this.

**Learning-page AI (Coach + quiz, `routes/curriculum.py`) must never hardcode a model id.** Both use
`DEFAULT_KIMI_MODEL` via `_create_completion()`, which falls back to it if an override
(`CURRICULUM_MODEL`/`KIMI_MODEL`) is unavailable. Provider errors go through
`_friendly_ai_error()`; never echo `str(e)` to the page. Hardcoded `moonshot-v1-*` ids that Moonshot
had retired broke both features until 2026-10-13 (see CLAUDE_RUNBOOK.md).

## Safety System (`src/agent/safety.py`)

`SafetyValidator.validate_tool_call()` classifies every tool into risk levels:

- **high_risk_tools**: All delete/terminate operations across all providers. Requires user confirmation. Escalates to `critical` if targeting production.
- **medium_risk_tools**: Update, restart, firewall rule, IAM, scale, cordon operations. Requires user confirmation.
- **low risk** (default): Create and read operations. No confirmation needed.

### Declared tool capability (governance refactor, Phase 1 — `src/agent/tool_capabilities.py`)

Risk now lives on the tool, resolved **before** the legacy name-sets below.
`validate_tool_call` computes the legacy risk, then reconciles it with
`tool_capabilities.resolve(name)` (module-declared `capability=` block →
`config/tool_capabilities.yaml` → `None`): a declaration can **raise** the risk
or hold it, never lower it — a more-lenient declaration is logged and ignored at
runtime, and `tests/test_tool_capabilities.py` fails the build on it.

- `config/tool_capabilities.yaml` is **generated** by `scripts/gen_tool_capabilities.py`
  from the legacy classification (legacy `high` → `permission: destroy`, `medium`
  → `modify`). Re-run it after changing the legacy sets; `tests/test_tool_capabilities.py`
  asserts it is not stale.
- The pentest gating and the three action-aware `manage_*` special cases run
  first and are unaffected. Production escalation (`high` → `critical`) still
  applies after the capability resolves.
- `mutating` / `reversible` / `produces` are recorded but not yet consumed (Phase
  5 rollback stack). Full spec: `docs/governance-refactor.md`.

**When adding new tools:**
- **Preferred:** add a `capability` block to the tool's `get_tools()` entry —
  `{'permission': 'destroy'|'deploy'|'modify'|'analyze'|'read', 'mutating': bool, 'reversible': bool}`.
- Otherwise run `python scripts/gen_tool_capabilities.py` to backfill
  `config/tool_capabilities.yaml`.
- `tests/test_tool_capabilities.py` fails if a medium/high tool has neither — the
  safety net the "remember to edit `safety.py`" step below never had.
- The legacy `high_risk_tools` / `medium_risk_tools` sets and prefix
  auto-detection remain as the **floor** (removed in a later phase once every
  module declares inline). The `<provider>_<verb>_<noun>` blind spot documented
  below still applies to the legacy layer, which is why the capability check now
  sits in front of it:
- Every new `delete_*` or `terminate_*` tool MUST be added to `high_risk_tools`
- Every new `update_*`, `restart_*`, `create_*_rule`, or IAM tool MUST be added to `medium_risk_tools`
- Forgetting this causes the tool to default to low risk with no confirmation prompt
- Auto-detection fallback: prefixes `delete_`, `terminate_`, `destroy_`, `remove_`, `drop_`, `purge_` are auto-classified as high risk even without explicit listing. Explicit sets take priority over auto-detection.
- **Auto-detection only matches the verb as a prefix of the tool name** (`name.startswith(...)`). A tool shaped `<provider>_<verb>_<noun>` (e.g. `git_delete_branch`, `pagerduty_update_incident`) is NOT caught by auto-detection even though `delete`/`update` appear in the name — it silently defaults to low risk unless explicitly added to `high_risk_tools`/`medium_risk_tools`. Check for this shape specifically when adding tools whose name doesn't start with the destructive verb.

**Current high-risk additions (beyond auto-detection):**
`abort_jenkins_build`, `delete_jenkins_build`, `terraform_destroy`, `terraform_state_rm`, `delete_sonar_project`, `nexus_delete_repository`, `nexus_delete_component`, `nexus_delete_asset`, `git_reset_to_commit`, `git_clean_working_directory`, `git_force_push_branch`, `git_delete_branch`, `git_delete_tag`, `resize_ec2_instance`, `execute_script` (shares `execute_command`'s risk — same underlying subprocess path), `docker_create_container` (unrestricted host bind-mounts, e.g. `/var/run/docker.sock`, give trivial container-escape to full host control — same risk class as `execute_command`; `_validate_container_volumes()` in `docker_tools.py` blocks the clearest cases as defense-in-depth), `get_secret_value` (GCP — discloses live secret plaintext into the chat/tool-trace/LLM-provider path, unlike every other secret-bearing tool in this codebase), `create_ec2_keypair` (AWS — returns the raw PEM private key material directly in the tool result, same disclosure class as `get_secret_value`; its `delete_ec2_keypair` sibling was already high-risk but the create path that actually discloses the secret was missed until the 2026-08-23 scheduled audit), `generate_s3_presigned_url` (AWS — generates an unauthenticated bearer URL, up to 7 days, for `get_object` or `put_object` with no further AWS auth required; same live-access-credential disclosure class, also caught by the 2026-08-23 audit), `list_storage_account_keys` (Azure — returns the raw storage-account access key, a full data-plane credential over every blob/file/queue/table in the account, into the chat/tool-trace/LLM-provider path; same disclosure class as `get_secret_value`/`create_ec2_keypair` — its mutating sibling `regenerate_storage_key` was then only medium-risk and this read path had no gate at all, caught by the 2026-09-15 audit; both are now high-risk), `regenerate_storage_key` (Azure — discloses the newly-generated key value the same way `list_storage_account_keys` does; was previously only medium-risk despite the identical disclosure shape as the high-risk tools above, escalated in the same audit), `terraform_state_pull` (returns the entire Terraform state file, which routinely stores sensitive resource attributes — DB passwords, TLS keys, API tokens — in plaintext; its `terraform_state_push`/`_move`/`_rm` siblings were already classified, also caught 2026-09-15), `terraform_output` (`terraform output -json` does not redact sensitive-marked outputs the way the default human-readable CLI format does — same disclosure class as `terraform_state_pull`, caught by the 2026-09-23 scheduled audit), `terraform_state_show` (prints every attribute, plaintext secrets included, of a single resource — same disclosure class scoped to one resource instead of the whole state file, also caught 2026-09-23)

**Current medium-risk additions:**
`disable_jenkins_job`, `cancel_github_workflow_run`, `rerun_failed_github_jobs`, `trigger_github_workflow`, `terraform_apply`, `terraform_state_move`, `terraform_import`, `terraform_force_unlock`, `terraform_state_push`, `terraform_workspace_delete`, `terraform_providers_lock`, `update_sonar_issue`, `assign_sonar_quality_gate`, `create_sonar_project`, `trigger_sonar_analysis`, `nexus_create_repository`, `nexus_run_cleanup_task`, `docker_build_image`, `git_clone_repository`, `git_switch_branch`, `git_merge_branch`, `git_rename_branch`, `git_reset_files`, `git_amend_commit`, `git_pull`, `git_push`, `git_cherry_pick`, `git_push_tag`, `git_stash_apply`, `git_stash_drop`, `git_stash_save`, `git_revert_commit`, `git_rebase_branch`, `git_grep_search`, `get_diff`, `git_diff_stat`, `git_show_file_at_commit`, `git_blame_file` (the last five are flag-injection-guarded by `_reject_flag_like` — see the git argument-injection guard section below — but classified medium as a human-review layer over the same class of git-flag primitive as the tools above), `github_close_pull_request`, `add_iam_user_to_group`, `create_eventbridge_rule`, `pagerduty_update_incident`, `opsgenie_acknowledge_alert`, `opsgenie_close_alert`, `opsgenie_escalate_alert`, `pagerduty_add_note`, `opsgenie_add_note`, `ansible_vault_encrypt`, `register_targets`, `pagerduty_create_incident`, `opsgenie_create_alert`, `publish_sns_message`, `subscribe_sns_topic`, `create_route53_record`, `publish_pubsub_message`, `send_sqs_message`, `github_create_repo`, `git_create_branch`, `git_fetch`, `git_create_tag`, `docker_pull_image`, `docker_create_network`, `docker_create_volume`, `create_datadog_event`

`trigger_sonar_analysis` is the same "kick off a remote job" shape as
`trigger_jenkins_job`/`trigger_github_workflow`/`create_gitlab_pipeline_trigger` (its `trigger_`
prefix isn't in the auto-detect list either); `ansible_vault_encrypt` joins its `ansible_vault_decrypt`/
`ansible_vault_view` siblings since it also mutates a file in place via the `ansible-vault` CLI.
`register_targets` joins its sibling `deregister_targets` (already auto-detected via the
`deregister_` prefix) — it can redirect live production traffic to an arbitrary instance/IP via a
load-balancer target group, but `register_` isn't an auto-detect prefix, so it defaulted to low
risk until the 2026-08-08 scheduled audit caught the asymmetry. `pagerduty_create_incident` and
`opsgenie_create_alert` joined their already-medium `pagerduty_update_incident`/
`opsgenie_acknowledge_alert`/`opsgenie_close_alert`/`opsgenie_escalate_alert` siblings after the
2026-08-19 scheduled audit — both page a live on-call engineer/team by default (PagerDuty defaults
`urgency` to `'high'`; OpsGenie's `create_alert` accepts a `responders` list), same
`provider_verb_noun` shape that defeats prefix auto-detection as the other alerting gaps above.
`publish_sns_message` and `subscribe_sns_topic` joined them after the 2026-08-23 scheduled audit —
`publish_sns_message` can page arbitrary email/SMS/HTTP subscribers with caller-controlled message
content, and `subscribe_sns_topic` can point all future topic messages at an arbitrary external
endpoint the caller supplies; neither name starts with an auto-detected prefix.
`create_route53_record` joined after the 2026-08-25 scheduled audit — its `action`
parameter defaults to `'UPSERT'` (its own tool description says so), silently overwriting any
existing live DNS record with the same name/type; `create_` isn't a monitored auto-detect prefix,
and its `delete_route53_record` sibling was already correctly high-risk via the `delete_` prefix,
so only the overwrite path had no gate at all.
`publish_pubsub_message` (GCP) joined after the 2026-09-02 scheduled audit — same shape as
`publish_sns_message`: `topic_name`/`message_data`/`attributes` are all caller-controlled, and
Pub/Sub topics commonly fan out to push subscriptions (arbitrary external HTTP endpoints) or
trigger downstream Cloud Functions/Cloud Run; its own `create_pubsub_subscription` sibling was
already medium-risk but the publish path itself had no gate.
`send_sqs_message`, `pagerduty_add_note`, and `opsgenie_add_note` joined after the 2026-09-15
scheduled audit — `send_sqs_message` is the same "pages a live downstream consumer with
caller-controlled content" shape as `publish_sns_message`/`publish_pubsub_message` (SQS queues
routinely trigger downstream Lambda/consumers); `pagerduty_add_note`/`opsgenie_add_note` post
caller-controlled content onto a live incident/alert, visible to every responder on it, and are
the same `provider_verb_noun` shape as the other alerting gaps above — every other write verb in
those modules (`create`/`update`/`acknowledge`/`close`/`escalate`) was already medium.
`git_stash_save` joined its already-medium `git_stash_apply`/`git_stash_drop` siblings the same
day — it's the one stash operation that actually reverts the working tree (discarding
uncommitted changes from view), and was the only one of the three without a gate.

`git_create_branch`, `git_fetch`, and `git_create_tag` joined after the 2026-09-24 scheduled audit
— all three are genuinely mutating (new branch/tag, fetching remote refs) and already call
`_reject_flag_like()` on their caller-supplied params (the argument-injection RCE class is not
open here), but had no risk classification at all, unlike comparably-benign siblings
(`git_switch_branch`, `git_add_remote`) already gated medium for the human-review/audit-trail
layer. `docker_pull_image` joined the same day — it's the one step in the pull/build/push chain
that actually introduces untrusted code onto the host (an arbitrary caller-specified image:tag
from a registry) and had zero risk classification, despite its `docker_build_image`/
`docker_push_image` siblings both already being medium. `docker_create_network`/
`docker_create_volume` joined too — lower severity, but the same "destructive op gated, its
creating counterpart isn't" asymmetry as `create_route53_record`/`github_create_repo` below
(their `docker_remove_network`/`docker_remove_volume` siblings were already high-risk via the
`remove_` auto-detect prefix).

`github_create_repo` joined after the 2026-09-01 scheduled audit — same permissive-default-`create_`
shape as `create_route53_record`: its `private` parameter defaults to `False`, so a repo created
without the caller explicitly passing `private=True` is published to GitHub with no confirmation,
while its `github_delete_repo` sibling was already correctly high-risk via the `delete_` prefix.

**Action-aware risk classification:**
- `manage_ec2_instance` — risk level depends on the `action` parameter:
  - `action='terminate'` → HIGH RISK (requires confirmation; escalates to CRITICAL on production instances)
  - `action in ('stop', 'reboot')` → MEDIUM RISK (requires confirmation)
  - `action='start'` → LOW RISK (no confirmation required)
  - This is implemented in `validate_tool_call()` with special-case logic that inspects the action param before returning the classification result
- `manage_vm` (Azure) — same pattern: `action in ('stop', 'restart', 'deallocate')` → MEDIUM RISK, `action='start'` → LOW RISK
- `manage_compute_instance` (GCP) — same pattern: `action in ('stop', 'reset')` → MEDIUM RISK, `action='start'` → LOW RISK

### SSRF guard for tools that call a caller-supplied URL (`src/utils/network_safety.py`)

`safety.py`'s risk classification gates *confirmation prompts* for DevOps actions — it does not
validate URLs/hosts, so any tool that takes a `base_url`/`url`/`*_url` parameter and makes an
outbound HTTP request is a potential SSRF vector (the param is ultimately driven by chat text).
**When adding a new tool that accepts a caller-supplied URL/host and calls out to it**, call
`assert_safe_url(url)` (raises `UnsafeUrlError`, a `ValueError` subclass — safe to let existing
`except Exception` handlers catch it) before making the request. It blocks loopback/link-local/
multicast/unspecified addresses (covers the cloud metadata endpoint `169.254.169.254` and the
app server's own local-only services) but **deliberately allows RFC1918 private ranges** — these
tools are designed to reach self-hosted internal infra (Jenkins/SonarQube/Nexus/Prometheus/K8s
service IPs almost always sit on private IPs), so blocking `is_private` would break their
intended use, not just close an attack path.

**`assert_safe_url()` only validates the URL you hand it — it has no say over what happens
next.** If the actual request then lets `requests` auto-follow redirects (the default), a server
that passed validation can 302 straight to a blocked target and `requests` will silently follow
it, since redirect-following happens inside urllib3 with zero knowledge of this app's SSRF
policy. **For any `requests`-based call, use `safe_request(method, url, **kwargs)`** (same
module) instead of `requests.get/post/etc.` directly — it re-validates every redirect hop before
following it, raises `UnsafeUrlError` on rejection, caps the chain at 5 hops, and strips
`Authorization`/`Cookie`/`auth=` on any cross-origin hop so a redirected base_url can't leak a
live credential to whatever responded with the redirect. Pass `validator=` if the call site needs
a stricter policy than `assert_safe_url` — **`assert_safe_external_webhook_url()`** (same module)
is the shared stricter policy for arbitrary user-configured *external* webhook endpoints
(Slack/Teams/generic outbound webhooks): it also blocks RFC1918/reserved/multicast ranges, since
there's no legitimate reason for a notification webhook to target private address space, unlike
the self-hosted-internal-tool trust model `assert_safe_url` is designed for. `api_gateway.py`'s
`_is_safe_webhook_url`/`_raise_if_unsafe_webhook_url` now delegate to it instead of duplicating the
ipaddress/socket logic; `services/notification_service.py`'s `SlackClient`/`TeamsClient` and
`app.py`'s `test_notification_channel` route were fixed to use it too (2026-07-25 — they were
still using plain `assert_safe_url`/its default `safe_request()` validator, which let a
user-configured Slack/Teams webhook or notification-channel-test URL reach RFC1918 addresses
inside the app's own network — see CLAUDE_RUNBOOK.md). `app.py`'s `_validate_webhook_url()` (the
creation-time check on `POST /api/notification-channels`, distinct from the `test_notification_channel`
route above) had the same gap independently: it reimplemented its own SSRF check with
`socket.gethostbyname()` (single IPv4 record only — misses IPv6/multi-record hosts) and
`except (gaierror, ValueError): pass` — **failing open** on DNS resolution failure, the opposite of
`assert_safe_external_webhook_url()`'s fail-closed `raise UnsafeUrlError`. Found by the 2026-08-19
scheduled audit and fixed by delegating to `assert_safe_external_webhook_url()` directly instead of
duplicating the ipaddress/socket logic — same lesson as `api_gateway.py`'s webhook guards above: a
fix to one copy of duplicated SSRF logic doesn't reach sibling copies on its own. For clients that don't go through `requests` at all, disable redirects at that client's
own level instead: `cicd_tools._disable_jenkins_redirects()` monkeypatches `python-jenkins`'s
wrapped session (no `allow_redirects` param exposed by the library); `git_clone_repository` passes
`multi_options=['-c', 'http.followRedirects=false']` to `Repo.clone_from()` (needs
`allow_unsafe_options=True` since `-c`/`--config` is normally blocked by GitPython — only safe
because the value is fixed and code-controlled, never derived from caller input). **Not addressed
by any of this:** DNS-rebinding (the IP validated vs. the IP actually connected to a moment later)
— a deliberately deferred, lower-priority residual gap; see CLAUDE_RUNBOOK.md.

Currently wired into: `sonarqube_tools._get_sonar_client`, `nexus_tools._get_nexus_client`,
`cicd_tools._get_jenkins_server` (+ the 3 Jenkins functions that build `jenkins.Jenkins()`
directly, plus `run_smoke_test`/`auto_rollback_deployment`), every Prometheus/Grafana
function in `monitoring_tools.py`, `git_tools._validate_git_url` (resolves both `https://` and
`git@host:` forms before `git_clone_repository`/`git_add_remote` will use them — git's HTTP
transport otherwise issues a real outbound GET to `/info/refs` against whatever host it's given),
`services/notification_service.py`'s `SlackClient.send_webhook`/`TeamsClient.send` (the
`webhook_url` is user-configured in Settings → Notifications), and
`services/api_gateway.py`'s `test_webhook()` (now matches the same `_is_safe_webhook_url()` guard
`trigger_webhook()` already had — `test_webhook()` had been skipping it and echoing the raw
response body back to the caller, which made it an SSRF response oracle), and
`services/sso_service.py`'s `_discover()`/`_exchange_code()`/`_validate_id_token()`/
`_fetch_userinfo()` (an org admin sets `metadata_url` for the `generic_oidc` provider via
`routes/organizations.py`'s `sso_settings`, and the discovery document itself supplies
`token_endpoint`/`jwks_uri`/`userinfo_endpoint` — all of it caller-controlled and previously
fetched with raw `requests.get/post`, reachable on every login attempt including against the
cloud metadata endpoint), and `aws_tools.associate_eks_oidc_provider()` (connects to the
cluster's own OIDC issuer host via a raw `ssl.get_server_certificate()` call — not `requests`,
so invisible to `scripts/check_security_invariants.py`'s AST check; guarded with `assert_safe_url`
directly since there's no `requests`-based call to route through `safe_request()`). Datadog/PagerDuty/OpsGenie tools hit hardcoded hosts and don't need it.

**Non-`requests` HTTP/network calls need the guard applied by hand.** The SSRF invariant checker
only scans for raw `requests.*` calls — a tool that reaches the network via `ssl`, `socket`,
`urllib`, or an SDK's internal HTTP client is invisible to it. When auditing for SSRF or adding a
new tool that connects to a caller-influenced host through one of these, call `assert_safe_url()`
by hand before connecting; don't rely on the automated check to catch it.

### Git argument-injection guard (`src/tools/git_tools.py`)

Distinct from the SSRF guard above: GitPython's `repo.git.<subcommand>(*args)` invokes the `git`
executable directly with an argv list — no shell involved, so this isn't the shell-injection class
`scripts/check_security_invariants.py` tracks. The bug is that **git itself treats a leading `-`
as an option regardless of argument position**, and several subcommands expose options that
execute arbitrary commands on the host: `git pull`/`git fetch --upload-pack=<cmd>`,
`git push --receive-pack=<cmd>`, and `git rebase --exec=<cmd>`. `git_pull`/`git_push`/
`git_force_push_branch`/`git_push_tag` passed caller-supplied `remote`/`branch`/`tag_name` as a
bare positional argument with no validation, so a chat-driven caller could set
`remote="--upload-pack=touch$IFS/tmp/pwned;true"` and reach command execution — independent of the
medium/high-risk confirmation gate on these tools (the confirmation prompt shows "pull from X", it
doesn't recognize X as a flag). `git_rebase_branch`'s `onto_branch` had the same shape with
`--exec=<cmd>`. Fixed with a shared `_reject_flag_like(value, param_name)` helper (raises
`ValueError` if `value.startswith('-')`) called before `_get_repo()` in every function that passes
a caller-supplied remote/branch/commit/tag value as a bare positional git-command argument:
`git_pull`, `git_push`, `git_force_push_branch`, `git_push_tag`, `git_rebase_branch`,
`git_switch_branch`, `git_delete_branch`, `git_merge_branch`, `git_rename_branch`,
`git_reset_to_commit`, `git_cherry_pick`, `git_delete_tag`, `git_revert_commit` — the last several
have no known RCE-capable flag but got the same guard for defense-in-depth given the ambiguity of
how each git subcommand's argument parser treats a dash-prefixed positional. **When adding a new
git tool that passes a caller-supplied ref/remote/branch string as a bare positional argument to
`repo.git.*`, call `_reject_flag_like()` on it first** — don't assume GitPython's lack of a shell
makes the value safe.

**2026-08-04 follow-up — the guard didn't cover every function that needed it.** A scheduled audit
found (and live-verified by actually running the exploit) that four functions added after the fix
above were still unguarded: `git_grep_search`'s `pattern` (`git grep
--open-files-in-pager=<cmd>` execs the pager — confirmed RCE), `get_diff`/`git_diff_stat`'s
`commit1`/`commit2` and `git_show_file_at_commit`'s `commit_sha` (`git diff/show --output=<file>`
writes to an arbitrary path — confirmed arbitrary file write), and `git_blame_file`'s `file_path`
(`git blame --contents=<file>` echoes an arbitrary file's contents back — confirmed arbitrary file
read, e.g. `/etc/passwd`). All five now call `_reject_flag_like()` and are classified medium-risk
in `safety.py` (see CLAUDE_RUNBOOK.md's 2026-08-04 entry). **This guard is opt-in per function, the
same structural gap the SSRF/login-timing checks in `check_security_invariants.py` were built to
close for their own patterns — it is not yet enforced by an automated check,** so don't assume a
new git tool is safe just because sibling tools in the same file are guarded; verify it directly.

**2026-08-12 follow-up — same gap, two more functions.** A scheduled audit found two functions
that predate the fix above and were never covered: `git_add_remote`'s `name` (`repo.create_remote(name,
url)` — a value like `name="-f"` is parsed by `git remote add` as an option instead of a literal
remote name, triggering an implicit fetch from the caller-controlled URL immediately on add,
before any confirmation step assumes data has been pulled) and `git_show_commit`'s `commit_sha`
(`repo.commit(commit_sha)` — GitPython's rev-parse can fall through to the `git` binary for specs
it can't resolve locally, the same dash-prefixed-positional ambiguity `_reject_flag_like`'s
docstring warns about; its sibling `git_show_file_at_commit` already guarded the identical
parameter). Both now call `_reject_flag_like()` and are classified medium-risk in `safety.py`.
**Confirms the "not yet enforced by an automated check" gap above is real, not theoretical** — a
security-focused audit still has to walk every bare-positional call site in this file by hand.

**2026-09-15 follow-up — third recurrence, one more function.** A scheduled audit found
`git_clone_repository`'s `dest_path` (fully caller-controlled, required in the tool's
`input_schema`) still unguarded: it's the trailing bare positional of
`Repo.clone_from(url, dest_path, ...)`, i.e. `git clone <options> <url> <dest_path>`, and git's
option parser permutes — a dash-leading `dest_path` is still parsed as a clone option even after
the URL. `dest_path="--config=core.hooksPath=/tmp/h"` runs attacker-chosen `post-checkout`/
`post-merge` hooks *during the clone itself*. GitPython's own `unsafe_git_clone_options` check
doesn't catch this — it only inspects `kwargs`/`multi_options`, never the positional `to_path`,
and is disabled outright in this function anyway (`allow_unsafe_options=True`, needed for the
`-c http.followRedirects=false` SSRF fix in the same call). Fixed with the same
`_reject_flag_like(dest_path, 'dest_path')` pattern as every other guarded function in the file
— see CLAUDE_RUNBOOK.md's 2026-09-15 entry. **Every other bare-positional git-subprocess
parameter in the file was re-walked by hand in the same audit and is guarded** — this appears to
close the gap for now, but per the note above, nothing stops the next new function from repeating
it.

## Security invariants (`scripts/check_security_invariants.py`)

SSRF gaps and login-timing side channels each got found and fixed independently, in a different
file, on four separate occasions before this existed — not the same bug regressing, but a
different piece of code each time that never got the guard (or reimplemented its own copy instead
of calling the shared helper). Both guards are opt-in per call site, so nothing structurally
stopped that from recurring. `scripts/check_security_invariants.py` is an AST-based scanner, run as
a pytest test (`tests/test_security_invariants.py`) so it's already gated by `ci.yml`'s `test` job
with no workflow changes, that fails the build if either pattern reappears:

1. A raw `requests.get/post/put/patch/delete/request(...)` call (handles import aliases) in
   `src/tools/`, `services/`, `routes/`, `api/`, or `app.py` — use `safe_request()` instead.
2. A direct `.check_password(...)` call in those same locations outside `routes/auth.py` — route
   through `routes.auth._run_timing_safe_password_check()` instead.

**If this test fails on code you're adding:** first try to route the call through `safe_request()`
/ `_run_timing_safe_password_check()`. **Only if the host is genuinely hardcoded (not
caller-influenced) or the check is in an already-authenticated context**, add an exemption comment
on the violating line or the line directly above it — `# ssrf-safe: <reason>` or
`# check-password-safe: <reason>` — with a specific, reviewed reason, not a blanket bypass. See the
37 existing exemptions across the codebase for the pattern (Datadog/PagerDuty/OpsGenie/GitHub's own
hardcoded API hosts, etc.).

**When adding a new recurring-pattern check to this file:** extract the core AST-walking logic into
a `_scan_source_for_<name>(rel_path, source)` function that takes source as a plain string, so it
stays unit-testable with synthetic strings independent of the real repo tree (see
`tests/test_check_security_invariants.py`) — the file-walking wrapper (`check_<name>()`) is a thin
layer on top that reads real files and applies the file-level exemption list.

## Concurrency Model: the shared `agent` singleton

**As of `db495f8` (2026-08-15, the chat-keepalive fix, PR #141), `devops-agent.service`
runs `--worker-class gthread --workers 3 --threads 8`** — real OS-thread concurrency
within each of the 3 processes, up to 8 requests interleaving in one process's memory
at once. This is a genuine change from the config this section previously documented
(3 plain sync workers, one request at a time per process, confirmed live 2026-07-30)
and it was **not called out in that PR's own CLAUDE.md diff** — found by a 2026-08-22
scheduled audit reading the committed `devops-agent.service` diff directly, not the
commit message. The switch is very likely intentional and correct: `/api/chat`'s
keep-alive now holds a connection open for up to `CHAT_MAX_TURN_SECONDS` (840s) per
turn, and a sync worker would have starved the whole pool on the 4th-plus concurrent
long-running chat. But it means the "no within-process race" reasoning this section
used to rely on **no longer holds** — real threads within one process can now
genuinely interleave on shared state, not just across the 3 processes as before.

The `_greenlet_local_property` mechanism below is unaffected and remains correct:
`threading.local()` isolates real OS threads exactly as well as it isolated
gevent-patched ones, so every property listed below is still safely per-request.
**What is NOT yet audited against this newly-real concurrency is other module-level
mutable state that was previously "safe by accident"** because only cross-process
(never cross-thread) interleaving was possible. Known candidates flagged by the
2026-08-22 audit, not yet fixed:
- `app.py`'s module-level `download_storage = {}` dict — writes to distinct
  per-turn keys are fine under the GIL, but this is worth a second look if any code
  path ever does a read-modify-write on it.
- `services/model_failover.py`'s module-level `PROVIDER_HEALTH` dict — `status['failures'] += 1`
  and similar are non-atomic read-modify-write ops on shared dict values; two
  concurrent failures on the same provider can now genuinely race within one process
  and undercount failures. Low severity (delays failover detection, not a security issue).
- `services/credit_service.py`'s `CreditService.deduct()` — plain read-then-write on
  `UserSubscription.credits_remaining` with no row lock (`with_for_update()`); two
  overlapping turns for the same user can now race intra-process, not just
  inter-process as before. Worth a locked/atomic update if this becomes a real
  revenue-accuracy issue.

None of these are known to be exploitable for privilege escalation or cross-user data
exposure — they're accuracy/reliability races, not the class of bug the `agent`
singleton fix below addresses. Treat this as a follow-up audit item, not an incident.

**Any per-request state on `DevOpsAgent` must be a `@property` backed by
`self._local` (a `threading.local()`, see `_greenlet_local_property()` in
`core.py`), never a plain instance attribute.** Gunicorn's gevent worker
monkey-patches `threading.local` to be greenlet-local, so this gives genuine
per-request isolation without touching any of the method bodies that read/write
`self.attr` — the same mechanism already used for per-user AWS/Azure/GCP
credential context (`_set_cloud_user_context`). A "save the original value,
restore it in `finally`" pattern is **not** sufficient — it looks like isolation
but does nothing to stop a different concurrent request from reading or
overwriting the value while the first request is waiting on I/O. See
CLAUDE_RUNBOOK.md's "Shared `agent` singleton leaked per-request state" entry for
the incident this pattern was built to prevent (a sandboxed/simulated destructive
action could execute for real if a concurrent non-sandbox request's flag won the
race). Current properties: `conversation`, `pending_download`,
`_current_user_id`, `_tools_override`, `_trust_tool_results`, `_sandbox_mode`,
`_current_conversation_id`, `_pending_approval`, `_last_tools_used`,
`_tool_event_callback` (the SSE tool-start/tool-done callback `app.py`'s streaming
route installs via `set_tool_event_callback()` for the duration of the tool loop —
found as a plain instance attribute during a routine audit, since it predated the
other properties; converting it closed a cross-request leak where one user's
tool events/`tool_trace` could be delivered to a different concurrent user's
stream). Use `default_factory` (not `default`) for any new mutable-valued
property, or an unset thread/greenlet's shared default becomes its own
cross-request leak the first time something mutates it in place.

**Any code path that runs a tool outside `process_message_isolated`/`process_message_streaming`
must call `agent._set_cloud_user_context(user_id)` itself** — those two entry points are the only
places that do it automatically. `services/approval_service.py`'s `_execute_tool()` (the
approve-and-run path for a previously-deferred high-risk tool call) was missing this call
entirely: `aws_tools._get_boto_client` hard-requires a user context, so an approved AWS action
either failed closed with "Authentication required" or could pick up whatever context a prior
request left on the greenlet. Fixed by setting `req.requester_id` as the context before running
the tool and clearing it in a `finally`, mirroring `core.py`'s own pattern.

**A 2026-09-06 scheduled audit found the same `_execute_tool` still missing the Execution
Integrity instrumentation added after it was last fixed.** It called
`agent.tools[tool_name](**tool_input)` directly with no `_audit_infrastructure_change` (no audit
row, and no purge from the synced-resource list for a destructive action), no `_record_tool_call`
(invisible to `usage_logs`), and no `_verify_and_annotate` (no read-back verification) — because
those three read `self._current_user_id`/`self._current_conversation_id`, which `_execute_tool`
never set alongside the cloud-credential context. The same audit also found that **Sandbox Mode
did not stop a real `ApprovalRequest` from being filed**: at all three tool-loop sites in
`core.py`, `validation.requires_confirmation` was checked *before* `self._sandbox_mode` (every
other branch in the same chain checks sandbox first), so a non-approver user in Sandbox Mode
asking to delete/terminate something got a real `ApprovalRequest` emailed to a real approver with
no sandbox marker anywhere, and — if approved — the tool ran for real. Both fixed the same day;
see CLAUDE_RUNBOOK.md's 2026-09-06 entry for the full detail and tests.

**Two more instances of the earlier context-setting gap, found by a 2026-08-15 scheduled audit and fixed the same
day:** `routes/api_gateway.py`'s `api_execute_tool()` (the `/v1/execute` developer-API direct tool
endpoint) called `all_tools[tool_name]['handler'](**params)` with no context set at all — same
fail-closed/stale-context risk as the `approval_service` bug, here on the Professional/Business-tier
REST API path. `routes/mcp.py`'s `_handle_tools_call()` (the MCP connector's tool-call handler) did
set context, but only via `aws_tools.set_user_context`/`clear_user_context` directly — AWS-only,
so an MCP client calling an Azure/GCP/`devops_operations_tools` tool ran with no context for that
provider. Both fixed by routing through `agent._set_cloud_user_context(user_id)` /
`agent._clear_cloud_user_context()` (imported via `from app import agent`), the same helper
`approval_service.py` uses, which covers all four providers.

**`_set_cloud_user_context`/`_clear_cloud_user_context` (`core.py`) must set AND clear every
provider's thread-local context, not just AWS/Azure/GCP.** `src/tools/devops_operations_tools.py`
(cost analysis, change governance, compliance tools) has the same `threading.local()`
set/get-context pattern as `aws_tools`/`azure_tools`/`gcp_tools`, and `_set_cloud_user_context`
did call its setter — but the module had no `clear_user_context()` at all, so
`_clear_cloud_user_context()` had nothing to call for it, leaving that thread's devops-operations
user_id stale after the request that set it finished (found by a 2026-08-11 scheduled audit; see
CLAUDE_RUNBOOK.md). When adding a new tool module with its own per-user thread-local context,
give it a `clear_user_context()` from the start and wire it into both halves of this method —
a setter with no matching clearer is the same class of gap as skipping the setter entirely.

## Cloudflare's idle-connection timeout vs. long agent turns

This site is proxied through Cloudflare, which enforces its own ~100s idle-connection
timeout on top of everything the app does — not configurable below Enterprise tier.
Any endpoint that can legitimately take longer than that (Kimi-tier swarm tasks are
explicitly designed to run up to ~290s) must send *something* back to the client
periodically, or Cloudflare kills the connection and returns a 524 to the user while
the backend keeps working, unaware the client already gave up. See
CLAUDE_RUNBOOK.md's 524 incident entry for how this was diagnosed live (a `499` in
nginx's log followed by a successful completion in gunicorn's own log ~25s later —
the backend wasn't broken, it just finished too late to matter).

`/api/chat` (`app.py`) handles this by running the actual agent call
(`_run_agent_call`) in a background thread while the view's generator
(`_generate_chat_response`, wrapped in `flask.stream_with_context`) streams a
whitespace keep-alive byte every `CHAT_KEEPALIVE_INTERVAL_SECONDS`
(module-level constant in `app.py`) back to the client for as long as the
thread is alive, then yields the real JSON body once it finishes.
`response.json()` (browser) and `json.loads()` (Python) both ignore
insignificant leading whitespace around a JSON value per spec, so this needed
zero frontend changes.

**`_run_agent_call` must wrap its body in `with app.app_context():`.**
`stream_with_context` only preserves the request/app context for the
generator it wraps (`_generate_chat_response`, which is why `current_user`/
`db.session` keep working in the post-agent-call code that lives there) — it
does nothing for a separate `threading.Thread` spawned alongside it. The
initial version of this fix (5e39d02) missed this: `_run_agent_call` ran
`agent.process_message_isolated()` with no app context of its own, so every
real (non-sandbox) tool call that resolves per-user cloud credentials via
`UserCloudCredential.query` (`services/credential_service.py`, hit by
literally every AWS/Azure/GCP tool) — plus `core.py`'s `_audit_chat_deletion`
destructive-action audit log — raised `RuntimeError: Working outside of
application context`, silently turned into a plain error-text response by
`_run_agent_call`'s own `except Exception`. Fixed the same day (2026-07-31);
see CLAUDE_RUNBOOK.md's follow-up entry. Any other endpoint that moves real
work onto a background thread for this pattern must do the same — re-enter
the app context inside the thread, never pass a live ORM object across the
boundary (same rule as `_dispatch_password_reset_email` and
`services/notification_service.py`'s async Slack/Teams dispatch) — rather
than a plain synchronous `jsonify(...)` return.

**The keep-alive converts "the request failed" into "the request succeeded and
then stopped mid-body", so the endpoint needs its own deadline and the client
needs a truncated-body branch.** Flushing that first whitespace byte commits
HTTP 200 *and the headers* to the browser ~15s in, long before the JSON body
exists. Anything that kills the worker after that point — gunicorn's
`--timeout`, a deploy restart, a dropped connection — leaves the client holding
a 200 whose body is nothing but whitespace, and `response.json()` reports only
`Unexpected end of JSON input`. The status code can no longer carry the failure.
Three rules follow, all load-bearing (see CLAUDE_RUNBOOK.md's 2026-08-13 entry
for the workflow run this cost):

- **`CHAT_MAX_TURN_SECONDS`** (default 840, env-overridable) bounds the
  keep-alive loop. It must stay comfortably under gunicorn's `--timeout` (900)
  so the *app* decides when to close the response, not the arbiter. On expiry
  the view emits a real JSON body with `still_running: true`; the turn keeps
  going on its thread.
- **Anything that must outlive the response belongs on the worker thread, not in
  the generator.** `_finalize_turn()` (usage log, assistant message, credit
  deduction, download token) is called by `_run_agent_call`, so a turn whose
  tools already changed real cloud infrastructure is still recorded when the
  client is gone. It re-queries every ORM object by id — never touch the request
  thread's session or `current_user` from there.
- **Read per-request agent state on the thread that produced it.**
  `agent.last_tools_used` / `agent.pending_download` are
  `threading.local()`-backed (`_greenlet_local_property`), so the request thread
  sees only its own empty defaults. Reading them in the generator silently
  logged every `/api/chat` turn as `action_type='agent_message'` with
  `tool_name=None` and dropped generated keypair downloads entirely, from the
  2026-07-30 keep-alive fix until 2026-08-13. Any new per-request agent state
  read outside `_run_agent_call` has this same failure mode.

Deploys must drain rather than guillotine: `--graceful-timeout 300` with
systemd `TimeoutStopSec=330` (`devops-agent.service`). gunicorn's *default*
graceful timeout is 30s, which no real agent turn can finish inside.

## Context Management & Progressive Tool Loading

Harness improvements that raise the agent's autonomy ceiling: Phase 1 (token-aware
context compaction + progressive tool loading) and Phase 2 (Anthropic prompt
caching). All have safe fallbacks and kill-switches and are unit-tested in
`tests/test_conversation_compaction.py`, `tests/test_tool_selection.py`, and
`tests/test_prompt_cache.py`.

### Token-aware context compaction (`src/agent/conversation.py`)
- `estimate_tokens(text)` — module-level, uses a cached tiktoken `cl100k` encoder
  if available, else a `len/4` heuristic. Never an HTTP round-trip (Anthropic
  `count_tokens` is too slow for the per-turn path); a slight over-estimate keeps
  budgets safely under the context window.
- `ConversationManager(max_history=20, token_budget=None, recency_keep=8)` —
  when `token_budget` is set, `_trim_history()` calls `_compact_old_tool_results()`,
  which **shrinks old `tool_result` bodies in place** (head 400 + tail 120 chars
  with a `…[compacted N chars]…` marker) until under budget. Compacting, not
  dropping, keeps every `tool_use`/`tool_result` pair intact and preserves
  resource IDs/ARNs (which live at the JSON head). The last `recency_keep`
  messages are never compacted. `token_budget=None` = legacy count-only behavior.
- Wired in `core.py`: `__init__` reads `self._context_token_budget =
  config.get('context.token_budget', 120000)`; both `process_message_isolated`
  and `process_message_streaming` construct `ConversationManager(token_budget=...)`.

### Progressive tool loading (`src/agent/tool_selection.py`)
Stops shipping all ~746 tool schemas on every request (token cost + worse tool
selection). Rides the **existing `_tools_override` hook** — no new plumbing.
- `classify_tool(name, module_category)` — AWS tools classified at the **service
  level** (`aws.ec2`, `aws.s3`, ...) so a single-service query selects ~30 tools
  instead of all 351; non-AWS tools use their module category. Categories are
  stored in `self.tool_categories` (populated in `register_tools_from_module`).
- `select_tool_definitions(defs, categories, message, max_tools, history_messages,
  connected_providers)` — matches the message to categories, always includes
  `command` + `devops_operations` + every name in `ALWAYS_TOOL_NAMES`, honors
  `max_tools`, and **returns `None` when nothing matches** (caller uses full list —
  never hide tools when unsure). Three signals, strongest first:
  1. **Explicit keyword matches** on the current message (`CATEGORY_KEYWORDS`).
  2. **`GENERIC_NOUNS`** — provider-agnostic words ("server", "database",
     "container", "cluster", "log") map to an ordered list of categories across
     AWS/Azure/GCP/K8s. Filtered to `connected_providers` when the caller knows
     which clouds the user linked, so "restart the web server" doesn't ship
     Azure+GCP tools to an AWS-only account.
  3. **`history_messages`** — the last `HISTORY_WINDOW` (6) user turns. Without
     this, follow-ups that carry no keywords of their own ("yes go ahead", "now
     delete it") matched nothing and fell back to shipping all ~746 schemas,
     which is the single largest avoidable latency source on the Kimi path.
- **`ALWAYS_TOOL_NAMES`** — `search_tools`, `record_state_override`, `http_check`
  and `tcp_check`, unconditionally. The last two are cheap read-only SSRF-guarded
  reachability probes (`src/tools/verification_tools.py`) the model needs to
  verify anything it just built ("is nginx serving on port 80") regardless of the
  turn's topic — without them it improvised (`git clone http://<ip>/`, reading the
  404 as success). `run_smoke_test` (in `cicd_tools`) is re-homed to the
  `verification` category via a `classify_tool` name override so it surfaces on
  "reachable / serving / health check" tasks too. The eight
  provider-generic escape hatches (`aws_api_read`/`write`, `azure_*`, `gcp_*`,
  `k8s_*`) that the system prompt tells the model to fall back on are now
  **scoped per turn** via `HATCH_PAIRS_BY_PROVIDER` / `_hatch_providers_for()`
  — only the providers this turn's matched categories (current message +
  generic nouns + history) actually implicate get their pair included. An
  earlier version of this fix made all eight always-present regardless of
  relevance, which meant a plain AWS request always carried GCP/Azure/
  Kubernetes hatches too — confirmed live 2026-09-02: `k8s_api_read` executed
  for a "create an ec2 instance using ubuntu" request purely because it was
  always offered, though nothing about the request implicated Kubernetes.
  Included by **name**, not by category, so a scoped hatch rides along
  without dragging its whole category in.
- **The `max_tools` cap never drops a category tied for the top explicit
  score.** "show me the pods in my eks cluster" scores `kubernetes` and
  `aws.eks` equally; the old greedy pass kept whichever sorted first and
  silently dropped the other, hiding exactly what was asked for. Weaker signals
  (generic nouns, history, the AWS seed) stay greedy and cap-bound — the four
  seeded AWS services are a *guess*, so they must not claim the cap-exempt
  slot, or a plain "what is my aws bill" ships ~197 tools past a cap of 100.
- `core._maybe_select_tools(message, max_tools)` runs after the user message is
  added in both entry points; it's a no-op if a caller passed an explicit
  `tools_override` or if `tool_selection.enabled` is false.
- **The chat routes must pass `max_tools=`, never `tools_override=`.** `_maybe_select_tools`
  opens with `if self._tools_override is not None: return`, so ANY caller-supplied override —
  including one that filters nothing — silently disables progressive loading for that turn.
  `app.py` did exactly this until 2026-09-02 via `scope_tools()`, whose docstring states it
  ignores `max_tools` and returns all ~742 tools reordered. Result: Kimi picked
  `nmap_port_scan` 150 times for "create an ec2 instance" and never called
  `create_ec2_instance`. The tell is that `"Progressive tool loading: N/M tools selected"`
  never appears in `logs/agent.log`. Guarded by `tests/test_tool_selection_engaged.py`.
- **Execution is restricted to the tools actually offered.** `core._is_tool_offered()`
  gates every one of the 5 tool-execution sites (2 Kimi non-streaming, 2 Kimi
  streaming, 1 Claude). Membership used to be tested against the full ~746-tool
  registry (`tool_name in self.tools`), so a model that emitted a name selection had
  deliberately withheld still got a real call against the user's cloud account —
  observed in production 2026-09-02. A withheld name now returns
  `_not_offered_result()`, which names `search_tools` as the recovery path; a
  genuinely nonexistent name still reports "Unknown tool". When `_tools_override`
  is `None` (full catalog sent) everything is allowed, so this is a no-op with
  progressive loading disabled. **Direct-execution paths outside the agent loop
  (`services/approval_service._execute_tool`, `routes/api_gateway.api_execute_tool`,
  `routes/mcp._handle_tools_call`) set no override and are unaffected** — they are
  authorized by their own gates, not by tool selection.
- **`search_tools` meta-tool** (registered in `core.__init__`, category `meta`):
  the ToolSearch escape hatch — searches the full catalog and expands
  `self._tools_override` so any filtered-out tool becomes callable next turn.
  **Scoring is whole-word with the tool name weighted 10x over the description**
  (partial name hits for terms of 4+ chars score 5). A plain substring test let
  short terms match inside unrelated words — "ami" hits "dyn-ami-c", which ranked
  `list_eks_clusters` above `create_ami` for the query "ubuntu ami", so the one
  recovery path from a filtered tool set returned junk.
  **Both Kimi tool loops must rebuild their OpenAI-format tool list on every
  iteration** via `core._current_oai_tools()`, never once before the loop. The
  handler appends recovered tools to `_tools_override` mid-loop and tells the
  model "these tools are now available — call them directly", but a list built
  before the loop never carried them; the model was handed a promise the next
  request contradicted, so it burned an iteration or answered "I don't have
  that tool". The Claude paths already re-read the override each iteration.
  This is the escape hatch's *only* recovery route on the free/starter tiers,
  so any new provider loop must re-read the override per iteration too.

### Prompt caching (`src/agent/prompt_cache.py`)
Phase 2 of the harness roadmap. Caches the static system prompt + tool schemas
(breakpoint 1) and the conversation prefix (breakpoint 2) via Anthropic
`cache_control` on the **Claude path only** — Kimi (OpenAI-compatible) uses a
different mechanism and is untouched. Pure helpers, unit-tested in
`tests/test_prompt_cache.py`.
- `STABLE_SYSTEM_PROMPT` (module constant in `core.py`) is the byte-stable system
  core, extracted from the old inline literal; the volatile tail (preferences/trial)
  is built by `build_volatile_tail` and left uncached. `_build_system_prompt_parts`
  returns `(stable_core, volatile_tail)`; `_build_system_prompt` joins them
  byte-identically for the Kimi/cache-disabled callers.
- `build_cached_system(core, tail)` puts `cache_control:{type:"ephemeral"}` on the
  core block (this also caches the tool schemas, which render before `system`).
- `apply_message_breakpoint(messages)` tags the last message's last block; it
  **deep-copies only the last message** so stored history is never mutated
  (otherwise breakpoints accumulate across the 50-iteration tool loop and exceed
  the 4-breakpoint limit → 400).
- Wired in `_call_claude_api` and the streaming path, gated by
  `prompt_cache.enabled`; `_log_claude_usage(response, streaming)` logs
  `cache_read`/`cache_write` tokens at both sites.
- **Known limits (by design, not fixed):** Phase 1 `_compact_old_tool_results` and
  the `search_tools` meta-tool both rewrite the prefix mid-turn and can invalidate
  breakpoint 2; **breakpoint 1 (system+tools) is the dependable win.** Short
  tool-result messages fall under the 2048-token cache minimum and won't cache.
  Verify hits via the `Claude usage:` log line (`cache_read > 0` from iteration 2).

### Repeated-failure guard (`core.py`)
`DevOpsAgent._repeat_guard` is a greenlet-local dict counting consecutive failures per
`(tool_name, canonical args)`. At `MAX_IDENTICAL_TOOL_FAILURES` (3) the call is refused with
an instruction to stop retrying; a success clears the count. It is reset at the top of both
`process_message_isolated` and `process_message_streaming` — gthread reuses worker threads, so
a stale count would block a legitimate call on the next request. **Wired into all three tool
execution paths** (Kimi non-streaming, Kimi streaming, Claude); adding a new execution path
means wiring both `_repeat_guard_blocked` and `_repeat_guard_record` into it, and
`tests/test_tool_selection_engaged.py` asserts the count of each is exactly 3.

### Fabricated action claims (`core.py`)

**"Did any tool run this turn?" is the wrong question to ask about a claim that
infrastructure changed.** `_hallucination_severity()` asks exactly that and returns `''`
the instant `tools_called_this_turn` is true; the call sites widen it further with
`tools_in_context = tools_called_this_turn or _history_has_real_resource_data(messages)`,
which stays true for the rest of a conversation once any real `vpc-`/`i-` id lands in
assistant history. On 2026-09-04 that let a single `get_aws_resource_inventory` call
disarm detection while Kimi reported a fully-detailed EC2 launch — instance id, VPC,
subnet, volume, public IP — with `create_ec2_instance` never called and nothing created.
The IDs were style-matched to real recon (`devops-keypair` real, private IP inside the
real us-east-1b CIDR, VPC/subnet ids invented), which is what made it convincing. See
CLAUDE_RUNBOOK.md's 2026-09-04 entry.

`_fabricated_action_claim(user_message, response_text, executed_tools, sandbox_mode)`
asks the per-claim question instead: **the response asserts a mutation completed — did a
tool that can actually perform that mutation run this turn?** `_ACTION_FAMILIES` holds
four families (create / destroy / power / modify), each a `(request verbs, completion
assertion, substantiating tool markers)` triple. The **request gate is what keeps read
flows quiet** — "describe my instance" answered with "launched on 2026-05-15" is
narration, not a claim — and the **completion assertion is past-tense only**, so "I could
not create it" and "before I launch it I need…" don't fire.

**Completion phrases are matched only when un-negated** (`_claim_asserted`). "No new
instance **has been created** yet" is an honest denial, and the agent produces exactly
that sentence when it declines to act — replacing it would destroy a correct answer that
was asking the user a question (caught 2026-09-05, before this guard shipped). The
lookback stops at a clause break (`.!?;:|` or newline), so a negation cannot launder a
real claim from an earlier sentence: "No errors occurred. The instance was created."
still fires. Un-negated matching fails **open** by design — "with no downtime, the
instance was created" is read as a denial and passes — because a false "nothing was
created" after a real mutation is the more damaging error.

- It runs **before** the severity check on both Kimi response paths and is deliberately
  **not** disarmed by unrelated tool calls or by history. On a hit the response is
  replaced with `_FABRICATED_ACTION_REPLACEMENT`, which says plainly that nothing changed.
- Executed tools come from `self._last_tools_used[executed_from:]`, with `executed_from`
  marked at loop start — `process_message_streaming` never resets that list, so an
  absolute read would pick up a previous turn's tools on a reused gthread worker.
- **`_UNIVERSAL_WRITE_TOOLS` substantiates every family** (the four `*_api_write` escape
  hatches, `execute_command`/`execute_script`, `terraform_apply`, the Ansible runners).
  A false "nothing was created" after a real mutation invites a duplicate resource, which
  is the more dangerous direction — when adding a tool that can perform arbitrary writes,
  add it here. A name that drifts out of the catalog silently stops substantiating
  anything; `tests/test_fabricated_action_claim.py` pins every name against the live
  registry (it already caught `ansible_run_playbook` vs the real `ansible_playbook_run`).
- Adding a mutation verb the families don't cover, or a new response path, means updating
  `_ACTION_FAMILIES` / wiring the guard; the test file asserts it appears on exactly 2
  response paths.
- **Claude paths (2026-10-19):** both end-turn exits call `_action_claim_verdict()`. The
  non-streaming path replaces like Kimi; the streaming path has already sent the text, so
  it can only append `_UNVERIFIED_ACTION_NOTE`. `_latest_user_text` skips Anthropic
  tool-result-only user messages, or the request would always read as empty. The weak/strong
  hallucination checks still run only on Kimi.
- **Follow-ups (2026-10-19):** a latest message with no action verb and no question
  ("okay", "this is the role: X") is checked against the previous 3 user messages by
  `_unverified_followup_claim`, which *appends* `_UNVERIFIED_ACTION_NOTE` rather than
  replacing. Claim regexes also cover in-progress wording ("creation is in progress",
  "state is CREATING"). History replay strips the app's own `_[Executing tool...]_`
  marker (`_strip_system_markers`); otherwise the model copies it and the strong check
  replaces real answers.

`_should_require_tool_use()` / `_TOOL_SIGNAL_RE` were **deleted** — they were defined and
never called from anywhere in the repo, so a guard that looked present in review enforced
nothing, and the regex only matched read verbs (`list|show|get|describe|…`), exempting the
create/delete requests where a fabricated success does the most damage. A test asserts the
helper does not come back without a call site.

### Config keys
- `context.token_budget` (default `120000`) — history compaction budget.
- `tool_selection.enabled` (default `true`) — kill-switch for progressive loading.
- `tool_selection.max_tools` (default `100`) — fallback cap when a caller doesn't
  pass `max_tools` (callers should pass `ModelConfig.max_tools`).
- `prompt_cache.enabled` (default `true`) — kill-switch for Anthropic prompt caching
  (Claude path only). When false, the system prompt is sent as a plain string.
- `mutation_verify.enabled` (default `true`) — kill-switch for post-create
  read-back verification (Execution Integrity rule 2, below).
- `tool_cache.enabled` (default `true`) — kill-switch for the 60s per-user
  read-result cache (Execution Integrity rule 5, `services/tool_cache.py`).
- `iac_fallback.enabled` (default `true`) — kill-switch for CloudFormation
  fallback generation on a failed create (Execution Integrity rule 4,
  `services/iac_fallback.py`).

## Execution Integrity

See [docs/execution-integrity.md](docs/execution-integrity.md) for the full
9-rule spec and the deferred-phase decisions. Phases 1–2 (shipped):

- **`=== EXECUTION INTEGRITY ===`** block in `STABLE_SYSTEM_PROMPT` — verified
  results only, eventual-consistency handling ("never call a <5-min-old
  resource 'not found'"), the (a)/(b)/(c) error classification, the
  retry→generic-API→IaC fallback order, and "console truth beats agent
  inference" on state disputes.
- **Service reachability** (2026-09-09) — four bullets in the same block:
  *SERVICE REACHABILITY* (use `http_check`/`tcp_check`/`run_smoke_test`, never
  infer HTTP reachability from another tool's error text — a live run had the
  agent `git clone http://<ip>/` and read the 404 as success); *A RESPONSE IS
  NOT SUCCESS* (a non-2xx/3xx or `matched_expected: false` = port open but app
  not serving what you intended — say exactly that); *NAME YOUR BLIND SPOTS*
  (no SSM / console / shell → your probe is your only evidence, don't narrate
  on-instance state you haven't read); *PROVISION THEN CONFIGURE IN ONE SHOT*
  (bake config into `user_data` on the first `create_ec2_instance` — don't
  launch bare, hit an IAM wall, and terminate+relaunch).
- **Prices** (2026-10-15) — *PRICES ARE ESTIMATES UNLESS A TOOL SAID SO*: a cost or
  price not read from a tool result this conversation must be labelled "estimate" with a
  pointer to the provider's pricing page (a GuardDuty answer quoted "~$1-5/mo" as fact).
  Pinned by `tests/test_price_estimates_labelled.py`.
- **Session resource registry** — a creating tool (`create_`/`run_`/`launch_`/
  `provision_`/`deploy_`, excluding `_rule`/`change_request`) that succeeds is
  recorded by `_audit_infrastructure_change` (renamed from
  `_audit_chat_deletion`, now handles `action_type='create'` too) with the
  conversation id in `change_details`. `_session_resource_context()` reads
  those rows back (last 30 min, same conversation) into the volatile prompt
  tail via `build_volatile_tail(..., session_context=)`, so a later turn won't
  report a just-created resource as missing. Per-turn ids also land in
  `agent._created_resources`.
- **Guard notes** — `_repeat_guard_result` and a ≥3× not-offered guess arm
  `_note_guard`; `_guard_notes_suffix()` appends a plain-language
  "Tool-selection note" to the user-facing response (never replaces it) so a
  misrouting/retry storm is visible to the user, not just logged.
- **Read-back verification** (Phases 2 / 2b / 2c, `services/mutation_verifier.py`
  + `_verify_and_annotate`) — after a create, delete **or update** tool
  succeeds, the resource's dedicated read tool is polled
  (`DEFAULT_BACKOFF = (0,1,2,5,7)s`, ≤3/turn) and a `_verification: {status:
  confirmed|unconfirmed, action: create|delete|update, ...}` key is added to
  the result. `unconfirmed` is **not** a failure — the read hasn't caught up
  (create), the resource is mid-shutdown (delete), the new value isn't live
  yet (update), or the read-back is failing. A read that errors for a
  non-NotFound reason is never read as "gone". Verifiable set: EC2 (+
  `manage_ec2_instance`: `terminate`→delete, `start`/`stop`/`reboot`→update),
  security group, VPC, RDS, S3, ECS service, Lambda config (see the doc).
- **Credit protection** (Phase 3, rule 5) — `_low_credit_warning()` attaches a
  `low_credit_warning` to the chat response / SSE `done` event when the balance
  is 1–5 (`LOW_CREDIT_THRESHOLD`); the UI toasts it (deduped on the value).
  `services/tool_cache.py`'s `READ_CACHE` caches successful **read** results by
  `(user_id, tool, args)` for 60s via `DevOpsAgent._invoke_tool` (all 5 exec
  sites); **any mutating call invalidates that user's whole read cache** so a
  stale read can't contradict a just-applied change.
- **IaC fallback** (Phase 4, rule 4, `services/iac_fallback.py` +
  `_iac_fallback`) — when a creating tool returns `{success: False}`, a
  CloudFormation template is built from the same intent and attached as
  `_iac_fallback` on the result, and `create_cloudformation_stack` is appended
  to `_tools_override` so the model can deploy it this turn. Supported: EC2
  instance (needs `ami_id`), security group, VPC, S3 bucket. One per turn;
  RDS omitted (password handling).
- **Destructive-action hardening** (Phase 5, v2.0 rules 3/4/10) — a
  delete/terminate `_verification` is `confirmed` only after **2 consecutive**
  `gone` reads (`DELETE_CONFIRMING_READS`), using the longer
  `DELETE_BACKOFF` (~57s); on `unconfirmed` the model re-issues the terminate
  (platform never auto-repeats). `_audit_infrastructure_change` (now called
  *after* verify — the 5 sites were reordered) writes
  `change_details.audit_trail` for every destructive row (tool_request
  redacted, verification `reads[]`, `final_confirmed_state`,
  `user_override_flag`) + an `audit_alert` on read disagreement.
  `agent.last_mutation_pairs` logs each mutation+verification unit. The
  always-available `record_state_override(resource_id, corrected_state,
  evidence)` tool lets the model flag a row when the user's console evidence
  wins (rule 9).
  **`_audit_infrastructure_change`'s `is_destructive` check is a tool-name
  prefix match and does not by itself cover action-aware tools.**
  `manage_ec2_instance` never starts with a destructive prefix, so a
  terminate through it produced no audit row / disagreement alert /
  `record_state_override` target at all until the 2026-09-09 scheduled audit
  added an explicit `action`-aware branch (`is_manage_terminate` folded into
  `is_destructive`, `is_manage_update` for `start`/`stop`/`reboot` as a new
  `update` row) — see CLAUDE_RUNBOOK.md. A future action-aware tool
  (`manage_vm`, `manage_compute_instance`) needs the same explicit branch;
  it will not be picked up by the prefix check.

Deferred (decisions recorded in the doc): Terraform generation, a `retry_queue`
subsystem, SG-rule / tag update verification, `check-errors.yml` wiring for
`destructive-audit-alert`.

**Partly fixed; flagged by the 2026-09-07 scheduled audit: four tool-execution paths bypass
`DevOpsAgent._invoke_tool`.** `services/approval_service.py`'s `_execute_tool()` (approve-and-run
for a deferred risky call) now calls `_record_tool_call`, `_verify_and_annotate` and
`_audit_infrastructure_change` itself, so an approved terminate is verified and audited — but it
still calls `agent.tools[name]` directly and so **never invalidates `READ_CACHE`**: a stale
pre-approval read can be served for up to 60s afterward. Since 2026-10-14 the two
direct APIs' **risky** calls run through the approval service and get all of it; their low-risk
calls, and an approver's medium-risk call, still run the handler directly. `routes/mcp.py`'s
`_handle_tools_call()` (MCP connector) still has **none** of it: no read-back verification, no `change_details.audit_trail` row, no cache
invalidation. Routing all four through `_invoke_tool` + verify + audit is the structural fix. See
CLAUDE_RUNBOOK.md's 2026-09-07 entry (re-checked 2026-10-14).

## Historical Fixes & Gotchas

See [CLAUDE_RUNBOOK.md](CLAUDE_RUNBOOK.md) for historical bug fixes and resolved issues.

## Knowledge Vault (`vault/`)

`vault/` is an Obsidian vault used as long-term project memory — the *why* behind
decisions and postmortems, complementing (never duplicating) CLAUDE.md (how things
work), CLAUDE_RUNBOOK.md (what was fixed), and WORKLOG.md (session state).

- **Reading:** at the start of nontrivial tasks, read `vault/INDEX.md` and follow
  only the links relevant to the task. Never bulk-read the vault.
- **Writing:** after making an architectural decision, solving a nonobvious bug, or
  learning why something is the way it is, write one atomic note in
  `vault/decisions/`, `vault/debugging/`, or `vault/architecture/` with YAML
  frontmatter (`date` in YYYY-MM-DD, `type`: decision | postmortem | rationale,
  `tags`), link related notes with `[[wikilinks]]`, and add a one-line entry to
  `vault/INDEX.md`.
- Notes are committed with the repo; `vault/.obsidian/` workspace state is gitignored.

## Adding a New Tool

### General Steps
1. Create handler function in the appropriate `src/tools/*_tools.py`
2. Register in `get_tools()` at the bottom of the same file with `{name, description, input_schema, handler}` — add a `capability` block for any mutating tool (`{'permission': 'destroy'|'deploy'|'modify', 'mutating': True, ...}`)
3. Risk classification: either the `capability` block in step 2, or run `python scripts/gen_tool_capabilities.py` to backfill `config/tool_capabilities.yaml`. Also add to the legacy `safety.py` set for a delete/update operation (still the floor — see Safety System section). `tests/test_tool_capabilities.py` fails if a medium/high tool has no declared capability.
4. Add sandbox mock branch in `services/learning_sandbox.py` if new tool module
5. Register the module in `app.py` with `agent.register_tools_from_module(my_tools)` (inside an `if config_manager.get('module.enabled', True):` guard)
6. Import the module in `src/tools/__init__.py` and add to `__all__`
7. Add teaching notes to `LEARNING_MODE_CONTEXT` in `app.py` if it's a new domain (e.g., a new CI/CD tool type)
8. Verify: `python -c "from src.tools.X import get_tools; print(len(get_tools()))"`

### Tool Registration Checklist (added for all 6 new modules — 2026-03-25)
All steps were completed and verified for: `cicd_tools`, `terraform_tools`, `sonarqube_tools`, `nexus_tools`, `docker_tools`, `ansible_tools`. Total tool count: **749** across 18 modules (`verification_tools` added 2026-09-09, `get_github_run_jobs` 2026-10-13). Tests: `tests/test_new_tools.py` (94 tests).

### Sandbox Mock Pattern
Each new tool module needs routing in `services/learning_sandbox.py → generate_mock_result()`:
```python
# Add detection flag at the top of generate_mock_result():
is_mymodule = any(k in tn for k in ('mymodule_keyword',))

# Add routing block:
if is_mymodule:
    return _mock_mymodule(tn, tool_input)

# Add mock function:
def _mock_mymodule(tool_name: str, tool_input: Dict) -> Dict[str, Any]:
    if 'list_' in tool_name:
        return {'success': True, 'simulated': True, 'items': [...]}
    # default fallback:
    return {'success': True, 'simulated': True, 'message': f'[Sandbox] {tool_name} completed'}
```
**Common gotcha**: substring matching is literal — `'list_jobs' in 'list_jenkins_jobs'` is `False`. Use the full function name substring (e.g., `'list_jenkins_jobs' in tool_name`) or a broader keyword.

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
        # Other API groups: bind them to this call's client
        # batch_v1 = client.BatchV1Api(_k8s_api_client())
        result = v1.api_call(...)
        return {'success': True, 'message': '...', ...}
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}
```
- `_get_k8s_client()` returns `(CoreV1Api, AppsV1Api)` bound to this call's own `ApiClient`. For other API groups use `client.BatchV1Api(_k8s_api_client())` after calling it; never `client.BatchV1Api()` with no argument (that is the process-wide default config, not the user's cluster).

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
- **`_get_azure_client()` imports and constructs only the requested `service_type`'s SDK client** —
  one `if service_type == '...':` branch per service, each with its own inline `from azure.mgmt.*
  import *ManagementClient`. Fixed 2026-08-25: it previously imported all seven `azure-mgmt-*` SDKs
  in one `try` and eagerly constructed all seven client objects on every call regardless of which
  one was requested, discarding six — the same "one broken/missing package takes down every
  service" bug already fixed in `gcp_tools.py`'s `_get_gcp_client()` on 2026-08-11 (see the GCP
  Pattern section below), just never ported to its Azure sibling. **When adding a new
  provider-client-dict-style constructor (or a new `service_type` here), import and construct only
  what that one call needs** — a shared multi-service constructor that builds every client up
  front is exactly this bug shape regardless of which provider file it's in.

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
- **Never add a symbol to a shared multi-name `from google.cloud import a, b, c` line.** Import each
  service's SDK lazily, inside the branch that needs it. `_get_gcp_client()` used to import five SDKs
  on one line, one of which (`sql_v1`) has no PyPI distribution, so `ImportError` disabled all five
  services — including the four whose packages were installed. See CLAUDE_RUNBOOK.md's 2026-08-11 entry.
- **Cloud SQL has no `google-cloud-*` client library** (`google-cloud-sql` is not a real PyPI package).
  Reach it via `_get_sqladmin_client()`, which builds a REST discovery client
  (`googleapiclient.discovery.build('sqladmin', 'v1beta4', ...)`) and fails closed on missing
  credentials. Do not write `from google.cloud import sql_v1` — it is guaranteed to raise at runtime,
  and `tests/test_gcp_credential_fail_closed.py` fails the build if one is reintroduced.
- Every GCP SDK client must be constructed with credentials from `_get_gcp_credentials_kwargs()`
  (which raises when the user has none linked). A client built with no `credentials=` argument
  silently falls back to Application Default Credentials — the app server's own ambient identity —
  instead of the requesting user's. This is enforced by an AST test over the whole module.

## Free Trial System

Free-tier users get **20 credits/month** with full agent experience — Kimi K3 with real tool execution.
**They refill monthly like every plan** (owner decision, 2026-10-14). Chat and `/api/v1` used to
skip the refill for free users ("one-time trial") while Billing refilled them. Every credit gate
now calls `UserSubscription.refresh_credits_if_due()`; the out-of-credits message
(`chat_service.generate_upgrade_pitch(refills_at)`) gives the refill date and Starter's real
allowance from `TIER_DEFINITIONS`. Guard: `tests/test_free_credits_monthly.py`.

### Model Tier Mapping

| Tier | Provider | Model | Tools | Max Tokens |
|------|----------|-------|-------|------------|
| free | Kimi | `kimi-k3` | Yes | 4096 |
| starter ($29/mo) | Kimi | `kimi-k3` | Yes | 4096 |
| professional ($99/mo) | Anthropic | `claude-sonnet-4-6` | Yes | 8192 |
| business ($299/mo) | Anthropic | `claude-opus-4-6` | Yes | 8192 |

Users can override tier default via chat toolbar toggle (`/api/model/switch`).

### Key Implementation Points

- **Kimi K3**: OpenAI-compatible API at `https://api.moonshot.ai/v1`. Requires `MOONSHOT_API_KEY`. Like the k2.7 line, it is a reasoning model — responses carry a `reasoning_content` field alongside `content` (the app reads `content`); it spends more completion tokens on reasoning, so keep `max_tokens` generous.
- **Tool format**: `_convert_tools_to_openai_format()` converts Anthropic format to OpenAI function-calling format.
- **Credit exhaustion**: Free users get 200 response with `trial_ended: true` (kept for the UI; it means "this month's free credits are used"), not 402.
- **Groq fallback**: Used when both Anthropic and Kimi are down. See `GROQ_FALLBACK_MODEL` in `chat_service.py`.
  The streaming route logs the main model's failure text (`Chat: ... using the backup model`) and,
  if Groq fails too, sends `fallback_failure_message()` instead of Groq's raw exception
  (2026-10-18: a dead `GROQ_API_KEY` turned every Claude hiccup into "Error code: 401 - Invalid
  API Key"). Guard: `tests/test_fallback_failure_message.py`.
- **Where the AI keys come from in production:** `devops-agent/production` in Secrets Manager
  overrides the server's `.env`, but only for names in `MANAGED_SECRET_KEYS`. The app reads
  `ANTHROPIC_API_KEY` (not `CLAUDE_API_KEY`). Anthropic keys created outside a workspace are
  refused without an `anthropic-workspace-id` header, so use a workspace key. The secret held
  only Brevo and Stripe keys from at least 2026-10-15 (startup logs say "Loaded 2 secrets"); the
  rest live in `.env`. The `diag-ai-keys` branch has a workflow that probes each key from the
  server and reports only status codes.

### Learning Mode & Sandbox

Users enable in Settings > Preferences:
- **Learning Mode** (`UserPreferences.learning_mode`): AI explains DevOps concepts, tracks proficiency
- **Sandbox Mode** (`UserPreferences.sandbox_mode`): Simulated tool results from `services/learning_sandbox.py`
- **Sandbox stands alone (2026-10-16).** The chat sidebar's Sandbox switch is always visible and
  turning Learning off no longer turns Sandbox off. In sandbox, `app._cloud_access_context()` sends
  `SANDBOX_CLOUD_ACCESS` instead of the real credential status, which said "NOT configured, do not
  call these tools" and made the agent send new users to add credentials. The chat welcome shows
  three practice missions (`SANDBOX_MISSIONS` / `renderSandboxWelcome()` in `index.html`) instead of
  the "Available Tools" card, and `SANDBOX_MODE_ADDENDUM` tells the agent to offer missions, not a
  tool list. Guard: `tests/test_sandbox_first_run.py`.
- **Sandbox goes one step per reply (2026-10-16).** The web-server mission once launched, tested
  and deleted everything in one reply. `SANDBOX_MODE_ADDENDUM` now says ONE STEP PER REPLY, the
  mission prompts ask for a pause, and `app._swarm_agents_for()` turns Kimi swarm off in sandbox
  (both chat routes use it). Practice ids are hex like real AWS ids (`learning_sandbox._rand_id`).
  Guard: `tests/test_sandbox_step_by_step.py`.
- **Learning Level** (`UserPreferences.learning_level`): `beginner`, `intermediate`, `advanced`

## Billing & Payments

See [CLAUDE_BILLING.md](CLAUDE_BILLING.md) for complete billing documentation including:
- Payment flow and webhook handlers
- NGN pricing table
- Stripe environment variables
- Setup scripts

## Environment Variables

Required:
- `ANTHROPIC_API_KEY` - Claude API key
- `SECRET_KEY` - Flask session secret

Optional:
- `CREDENTIAL_ENCRYPTION_KEY` - For credential encryption
- `DATABASE_URL` - Database connection string. **Required in production as of
  2026-09-12**: `app.py` used to default to
  `postgresql://devops:devops_local@localhost:5432/devops_agent` — a hardcoded,
  well-known credential shared with `docker-compose.yml` — which meant a
  production process that lost its `DATABASE_URL` would silently try a local
  database instead of failing. It now raises at startup when `DATABASE_URL` is
  unset and `FLASK_ENV=production` (or `USE_AWS_SECRETS=true`); outside
  production it still builds a local default, now from
  `DEV_DB_USER`/`DEV_DB_PASSWORD`/`DEV_DB_HOST`.
- `DEVOPS_AGENT_HOST_TOOLS` - `true` registers the tools that act on this server (shell commands,
  git, docker, terraform, ansible) and enables `/api/sandbox/run`. Self-hosted installs only; leave it
  unset on the hosted site (2026-10-22).
- `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` — consumed by
  `docker-compose.yml` only. **`POSTGRES_PASSWORD` has no default and compose
  refuses to start without it** (`${POSTGRES_PASSWORD:?…}` on both the `db` and
  `app` services): that database publishes 5432 to the host, so a shipped
  default would be a known credential on every developer's machine. Set it in
  `.env` — `.env.example` carries the key and a generator command. By contrast
  `docker-compose.sonar.yml` does keep a fixed `sonar`/`sonar` pair, because its
  Postgres binds no host port and is reachable only from that compose network.
- `FLASK_RUN_HOST` - interface the **development** server (`python app.py`) binds
  to. Defaults to `127.0.0.1` as of 2026-09-12; it previously hardcoded
  `0.0.0.0`, exposing the dev server to the whole network. `docker-compose.yml`
  sets it to `0.0.0.0` explicitly, since a container must bind all interfaces for
  its published port to be reachable. Production serves via gunicorn and never
  reaches this line.
- `STRIPE_SECRET_KEY` - Stripe payment processing (see Billing section above)
- `BASE_URL` - App base URL for Stripe callbacks (default: `https://devopsagent.io`)
- `MOONSHOT_API_KEY` - Kimi API key (required for Kimi model provider)
- `KIMI_MODEL` - Kimi model override (default: `kimi-k3`, the latest). Valid Moonshot ids (verified live via `/v1/models` 2026-07-22): `kimi-k3`, `kimi-k2.7-code`, `kimi-k2.7-code-highspeed`, `kimi-k2.6`, `kimi-k2.5` (no bare `kimi-k2.7`).
- `METRICS_TOKEN` - Bearer token gating `/metrics` (see Prometheus Metrics section below). Unset = endpoint returns 403, disabled by default.
- `PROMETHEUS_MULTIPROC_DIR` - Set in `devops-agent.service` (not `.env`) to enable multiprocess metric aggregation across gunicorn's 3 workers. Unset in local dev/tests — falls back to a single process-local registry.

### Prometheus Metrics (`/metrics`)

`routes/metrics.py` + `services/metrics_service.py`. Records `http_requests_total`
and `http_request_duration_seconds` (labeled `method`, `endpoint`, and `status`
on the counter) for every request via `before_request`/`after_request` hooks
wired in `app.py`. `endpoint` is Flask's matched route name (`request.endpoint`),
not the raw path — unmatched routes (404s, bot path-scans) collapse into one
`unmatched` label instead of creating unbounded cardinality from raw paths.
Duration buckets extend to 900s (`_DURATION_BUCKETS` in `metrics_service.py`)
to keep resolution on slow `/api/chat` turns, which legitimately run up to
`CHAT_MAX_TURN_SECONDS` (840s) — default prometheus_client buckets top out
at 10s and would collapse all of those into `+Inf`.

**Auth:** `/metrics` requires `Authorization: Bearer <METRICS_TOKEN>` — nginx.conf
proxies every path straight through to the app (no reverse-proxy scoping the
way node_exporter's `127.0.0.1`-only bind does), so this can't rely on network
position the way host-level monitoring does. Same shape as the existing
`/init-database-secret-endpoint-12345` token gate. Set `METRICS_TOKEN` in the
box's `.env` (not `MANAGED_SECRET_KEYS` — `init_secrets()` only overwrites keys
in that list, so a plain `.env` value is left alone in production).

**Multiprocess aggregation is required, not optional, in production.**
`devops-agent.service` runs `--workers 3` (3 OS processes) — a bare
`prometheus_client` registry is process-local, so scraping through gunicorn
would return whichever worker handled that request, with counters appearing
to jump or reset across scrapes. `render_metrics()` uses `MultiProcessCollector`
when `PROMETHEUS_MULTIPROC_DIR` is set. Three pieces have to stay in sync or
this silently breaks:
1. `PROMETHEUS_MULTIPROC_DIR` set in the systemd unit (must exist before the
   metric objects are created at module import time — set via `Environment=`,
   not `.env`, so it's present before gunicorn even forks).
2. `ExecStartPre` wipes and recreates that directory on every start — a stale
   file from a previous run's PID would otherwise be misread as a live
   worker's counters.
3. `gunicorn.conf.py`'s `child_exit` hook calls `multiprocess.mark_process_dead(worker.pid)`
   — without it, a crashed or recycled worker's metric file is never marked
   dead and gets double-counted alongside its replacement's for the rest of
   that service's uptime. Wired via `ExecStart --config gunicorn.conf.py`.

**Deploy gap:** `ci.yml`'s deploy job only does `git reset --hard` + `pip install`
+ `systemctl restart` — it does not copy `devops-agent.service` to
`/etc/systemd/system/` or run `daemon-reload`. Any future change to the systemd
unit (this one included) must be applied to the box manually via SSM, same as
this feature's initial rollout — the repo copy is documentation of the intended
unit, not the deployed one, until this gap is closed.

### Email MFA delivery (`email` mfa_method)

2FA methods are **email code** and **authenticator app (TOTP)**. TOTP needs no
config; it's computed locally with `pyotp`. **Email codes require a delivery
provider**, or login fails with "Failed to send verification email".

2FA lives on the account (`User.mfa_method` / `two_factor_secret`), never on a device.
The code screen stays valid for `_MFA_PENDING_MINUTES` (10, the email OTP lifetime).
Keep these two equal, or emailed codes expire on the screen while still valid.
`_check_mfa_code` strips whitespace and dashes before checking. The code box must not
cap input at 6 characters: a pasted "123 456" would be cut to 5 digits. Both MFA
screens show which account is signing in. Pinned by `tests/test_2fa_code_acceptance.py`.
Both email-code screens offer **Resend code** with a 60s cooldown (`User.can_resend_otp()`):
login uses `/api/2fa/resend-otp`, setup uses `/api/mfa/resend-setup-code` (signed in, 3 per 5
min, refused once email codes are on). Setup had none until 2026-10-16, so an expired code meant
starting over. Pinned by `tests/test_mfa_setup_resend.py`.

- Email (`services/email_service.py`): set `EMAIL_PROVIDER` (`brevo|smtp|sendgrid`)
  + `EMAIL_FROM`, then one of: `BREVO_API_KEY`; `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASS`; `SENDGRID_API_KEY`.

**SMS codes were removed on 2026-10-03.** They were never delivered, because
Brevo SMS needs prepaid credits plus a registered sender ID per country.
`services/sms_service.py` and `/api/mfa/phone/*` are gone, and
`/api/mfa/set-method` rejects `sms`. A user still stored as `mfa_method='sms'` is
migrated to `email` by `login()` on their next sign-in, so nobody is locked out. The
`phone_number`/`phone_verified` columns are kept. Don't reintroduce SMS without
first proving delivery end-to-end.

**Secrets Manager:** all of these are in `MANAGED_SECRET_KEYS`
(`services/secrets_manager.py`), so in production (`FLASK_ENV=production` or
`USE_AWS_SECRETS=true`) `init_secrets()` loads them from the
`devops-agent/production` JSON secret into the environment at startup. Add the
email keys to that secret — `SMTP_USER`/`SMTP_PASS` alone are insufficient
(without `SMTP_HOST` the app defaults to Brevo's relay and a non-Brevo SMTP
credential fails to authenticate).

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

Tests run against **SQLite in-memory** (forced in `tests/conftest.py`, overriding
`DATABASE_URL`) — Postgres is not required to run the suite. Current suite:
**about 1,412 tests** (~5 minutes; verified 2026-10-14). Three are environment-dependent and
fail in a bare sandbox but pass in CI: two `test_network_safety.py` tests need public DNS, and
`test_api_tools_execute.py::test_initialize_agent_populates_config` needs `ANTHROPIC_API_KEY` set.
**The whole suite shares one in-memory SQLite connection.** `app.py` drops `pool_recycle` for
SQLite URLs: with it, the connection was recycled 300s into the run and every later test saw an
empty database ("no such table"). The suite takes about five minutes, so it sat on that edge.
`tests/test_stripe.py` and `tests/test_secrets_manager.py` are
diagnostic scripts that hit live Stripe/AWS APIs; they are excluded from pytest
collection (`collect_ignore` in `conftest.py`) and run directly instead.

### Static analysis (SonarQube)

`docker-compose.sonar.yml` + `scripts/sonar-scan.sh` run a local SonarQube
server for analysing this repo; `.github/workflows/ci.yml` has a matching
SonarCloud job. Full operator guide, including which findings must **not** be
auto-fixed, is in [docs/sonarqube.md](docs/sonarqube.md).

```bash
docker compose -f docker-compose.sonar.yml up -d
./scripts/sonar-scan.sh --coverage        # http://localhost:9000
```

**Sonar does not know this codebase's security invariants and will recommend
changes that break them.** The duplicated four-step guardrails pipeline, the
`safety.py` risk sets, `_reject_flag_like`/`assert_safe_url` call sites, and
`routes/auth.py`'s deliberately-uniform timing all read to Sonar as duplication,
redundancy, or dead computation. Findings in those files get reviewed by a
human, never bulk-applied — `docs/sonarqube.md` lists them.

Other deliberate findings to leave alone: `models.py`'s fixed PBKDF2 salt in
credential key derivation (changing it makes every stored credential
undecryptable), SHA-1 in `associate_eks_oidc_provider` (AWS mandates SHA-1
thumbprints) and in legacy `sha1=` webhook HMAC verification, `http://` for S3
website endpoints and ip-api.com's free tier (HTTP-only), and `Access-Control-Allow-Origin: *`
on the public `/.well-known/oauth-*` discovery documents.

`scripts/sonar-scan.sh` stores the local server's admin password and scanner
token in `.sonar-token` (gitignored) on first run. After a
`docker compose -f docker-compose.sonar.yml down -v`, that file is stale: put
a freshly generated token in its `SONAR_TOKEN` line or the scan fails auth.

All S3 backup uploads go through `services/backup_upload.upload_backup_to_s3()`,
which sets `ExpectedBucketOwner` (from `BACKUP_S3_BUCKET_OWNER`, else the
caller's own account via STS) — never call `upload_file` for a backup directly.

## Dependency Pinning Policy

`requirements.txt` is **fully `==`-pinned** (since 2026-07-15, PR #50). Never
add or loosen an entry to `>=`: the EC2 deploy runs `pip install -r
requirements.txt` on every push to main, so a loose floor means untested
releases reach production unreviewed — a broken `coverage` release took CI down
for 5 days this way (see CLAUDE_RUNBOOK.md). To upgrade a dependency: change
the pin in a PR, let CI run the full suite against it, then merge. Security
floors from `pip-audit` findings become exact pins at (or above) the fixed
version, with the advisory ID in a trailing comment.

## CI / Security Scanning

GitHub Actions workflows live in `.github/workflows/`:

- **`ci.yml`** — runs on `push`/`pull_request` to `main`/`develop`. Includes a
  `security` job (`pip-audit`, `safety`, `bandit`) that fires only on those events.
  All security-job steps are `continue-on-error` — audit findings never fail the
  pipeline; only `test` and `build-check` gate the merge/deploy (`status-check` job).
  The test job installs `'coverage>=7.15.2'` explicitly — 7.15.1 crashed the HTML
  coverage report on Jinja-traced templates and took CI down Jul 13–15 (see
  CLAUDE_RUNBOOK.md).
  On push to `main`, also runs a `deploy` job (after all checks pass) that deploys
  to EC2 (instance `i-09af962714b13f9bc`) via **AWS SSM** (`AWS-RunShellScript`) —
  no inbound SSH / port 22 required. Git pull on the instance uses the read-only SSH
  deploy key (`/home/ubuntu/.ssh/deploy_key`). Port 22 on the security group is
  restricted to the operator's IP; SSM is the only automated deploy path.
- **`deploy.yml`** — **manual/backup** deploy-only workflow (`workflow_dispatch`
  only — no longer push-triggered, so it doesn't race ci.yml's auto-deploy). Uses
  AWS SSM to run the deploy script on EC2 (no inbound SSH / public IP needed).
  Authenticates via GitHub OIDC (see below) + requires the `EC2_INSTANCE_ID`
  GitHub secret. SSM setup is in place in the current account (`188046727805`):
  IAM role `devops-agent-ssm-role` (`AmazonSSMManagedInstanceCore`) attached to the
  instance via profile `devops-agent-ssm-profile`, agent Online. The private-repo
  pull uses a **read-only SSH deploy key** on the box
  (`/home/ubuntu/.ssh/deploy_key`, wired through the repo's `core.sshCommand`) so no
  token is ever passed through SSM command parameters/CloudTrail. Deploy targets the
  real layout: repo `/var/www/devops-agent`, venv `…/venv`, health on port `8000`.
  `ci.yml` also has a **`sonarcloud`** job (added 2026-09-12) that runs after
  `test` and reuses that job's `coverage.xml` artifact rather than re-running the
  suite — which is why the `coverage-report` artifact now uploads `coverage.xml`
  alongside `htmlcov/`. It reads the `SONAR_TOKEN` secret (the `env:` block at
  the top of the job is the only place that name appears). GitHub cannot rename
  a secret, and a token under any other name is never read and fails *exactly*
  like an invalid one — that cost three debugging cycles here while a valid
  token sat in a secret named `SONAR_TOKEN1`. It **skips itself cleanly
  until BOTH that secret and the `SONAR_ORGANIZATION` repo *variable* are set**,
  so it is inert until SonarCloud is configured (setup steps in
  `docs/sonarqube.md`). Checking only the token was not enough and shipped red:
  this repo already had a stale `SONAR_TOKEN` secret but neither variable, so the
  job ran and 403'd — a token alone cannot authenticate, since
  `sonar.organization` has no default. **That 403 is deeply misleading and cost
  three debugging cycles:** the scanner prints "Please check the property
  sonar.token or the environment variable SONAR_TOKEN" for a missing
  *organization* too, and `api.sonarcloud.io/analysis/jres` — the endpoint it
  fails on — answers 200 unauthenticated, so a 403 there always means a token was
  sent and rejected, never that none was sent. A `Verify the SonarCloud token`
  pre-check step now isolates the credential from the configuration before the
  scan runs, printing only an HTTP status. The
  `SONAR_PROJECT_KEY` variable stays optional because `sonar-project.properties`
  already sets `sonar.projectKey`; the guard only appends `-Dsonar.projectKey`
  when the variable is non-empty, because passing it unconditionally sent an
  empty `-Dsonar.projectKey=` that clobbered the properties file's value. **A
  guard over a multi-value integration must check every value that has no
  default, not just the secret-shaped one.** It is deliberately **not** in
  `status-check`'s `needs`, so a SonarCloud outage or an expired token can never
  block a deploy — promoting it to a hard gate means adding it there and checking
  its result. SonarCloud's default **Clean as You Code** gate only measures *new*
  code, so the existing ~121k lines stay a legacy baseline instead of failing
  every PR with a five-figure backlog.
- **`security-scan.yml`** — routine vulnerability scan on a **daily cron
  (`0 6 * * *`, 06:00 UTC)**, independent of pushes/PRs. Also runnable on demand
  via `workflow_dispatch` (Actions tab → "Scheduled Security Scan" → Run workflow).
  Runs `pip-audit` + `safety` (dependency CVEs) and `bandit` (source linter);
  uploads `scheduled-bandit-report` artifact (30-day retention). Steps use
  `continue-on-error` so one tool failing doesn't abort the others.
- **`main-push-guard.yml`** — fires on every push to `main` and **fails the build if the
  head commit did not arrive via a merged pull request** (queried through
  `repos/{repo}/commits/{sha}/pulls`). This exists because **`main` cannot actually be
  protected on this account**: GitHub gates *both* classic branch protection and rulesets
  behind a paid plan for private repos, and this repo is private on the free tier (the API
  returns `403 Upgrade to GitHub Pro or make this repository public` for both). That is also
  why `gh pr merge --auto` merges *immediately* here rather than waiting for checks — there
  is no protection rule for it to consult, so **always poll for green and merge explicitly**
  instead of relying on `--auto`. The guard is **detective, not preventive**: it cannot stop
  a direct push, only turn `main` red afterwards. Escape hatch: `[skip-pr-guard]` in the
  commit message (greppable in `git log`, so bypasses stay auditable). It passes rather than
  fails on a transient API error, so a GitHub outage can't block the pipeline.
  **If branch protection ever becomes available, replace this with a real required-status-check
  rule and delete the workflow.**
  The preventive half is **`.githooks/pre-push`**, which blocks direct pushes to `main`
  client-side. Hooks are not installed by cloning — each developer must run
  `git config core.hooksPath .githooks` once. It is bypassable with `git push --no-verify`
  (the CI guard still catches the commit) and only protects machines where it's configured.
- **`check-errors.yml`** — on-demand (`workflow_dispatch`) production log/error
  report: pulls `journalctl` errors/warnings, tool-call failure counts, guardrail
  violations, and 7-day usage stats off the EC2 instance via SSM. Authenticates
  via the same GitHub OIDC role as `ci.yml`/`deploy.yml` (migrated 2026-07-24 —
  it was missed by the #64 OIDC migration below, so it kept referencing
  `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` after those secrets were deleted and
  broke with "Could not load credentials from any providers" on every run from
  2026-07-23 onward).

- **`mcp-diagnose.yml`** — on-demand (`workflow_dispatch`). Run it right after a failed
  claude.ai connector "Connect". It prints MCP/OAuth request lines with status codes (gunicorn
  and nginx), the app's `MCP auth:` log lines (shows whether the Bearer header arrived and
  whether the token was found), the `mcp_oauth_*` table schemas, and recent token
  **metadata** (never token values). Same OIDC + SSM pattern as `check-errors.yml`.
  **If the log shows `/mcp/oauth/token` 200 and then no `/mcp` request at all, the block is at
  Cloudflare, not in the app.** The Cloudflare custom rule "AI Crawlers" blocks any user agent
  containing `Claude-User` (plus other AI agents) everywhere except `/robots.txt`; Claude's
  token-bearing MCP calls were stopped there, and claude.ai reported it as "the integration
  rejected the credentials it just issued". The rule now also exempts paths starting with `/mcp`
  and `/.well-known/oauth`. Keep those exemptions if the rule is ever regenerated (CLAUDE_RUNBOOK.md,
  2026-10-13).

Note: a feature-branch push does NOT trigger `ci.yml`'s scan (only `main`/`develop`
do). The scheduled scan is the only timer-based scan.

### Required GitHub Secrets for Deploy

| Secret | Used by | Purpose |
|--------|---------|---------|
| `EC2_SSH_KEY` | ~~none~~ | No longer needed — both deploy paths use SSM, not SSH |
| `AWS_ACCESS_KEY_ID` | ~~none~~ | No longer needed — deploys authenticate via GitHub OIDC (2026-07-18) |
| `AWS_SECRET_ACCESS_KEY` | ~~none~~ | No longer needed — deploys authenticate via GitHub OIDC (2026-07-18) |
| `EC2_INSTANCE_ID` | `ci.yml`, `deploy.yml` | EC2 instance ID for SSM targeting |

Every AWS-touching workflow (`ci.yml`, `deploy.yml`, `check-errors.yml`,
`run-migration.yml`) reads the role from the repo **variable** `AWS_DEPLOY_ROLE_ARN`
and the region from `AWS_REGION`, falling back to the values below — so moving
accounts is `gh variable set`, not a code change (`tests/test_aws_account_migration.py`
fails on a hardcoded role or long-lived keys). `run-migration.yml` still used the
deleted access-key secrets until 2026-10-13 and could not authenticate at all.
Deploy jobs assume `arn:aws:iam::188046727805:role/github-actions-deploy` via
GitHub OIDC (`token.actions.githubusercontent.com` provider; trust scoped to
`repo:shittuay/DevOps-Agent:*`; permissions = SSM SendCommand on the app
instance + GetCommandInvocation only). No long-lived AWS keys exist in GitHub.

## Adding a New Model

1. Define in `models.py`
2. **Migration is automatic** — restart the server and `app.py` startup will run `ALTER TABLE ADD COLUMN IF NOT EXISTS` for any missing columns. New tables are created by `db.create_all()`.
3. For manual/immediate migration without restart: `python migrate_missing_columns.py` or `POST /api/run-migration` (browser console, must be logged in)
4. Add API routes in `app.py` or appropriate `routes/*.py`

## Admin Access

### Role Hierarchy

| Role | Level | Description |
|---|---|---|
| `admin` | 4 | Full access — user management, audit log, system settings |
| `approver` | 3 | Can approve high-risk tool actions |
| `user` | 2 | Standard access (default for new signups) |
| `viewer` | 1 | Read-only |

Enforced by `@admin_required` / `@approver_required` decorators in `services/rbac.py`.

**This is a platform-wide role, distinct from `OrganizationMember.role`** (`owner`/`admin`/`member`, used by `organizations.py`/`services/multi_tenancy.py` for team management) — the two never cross-check each other. A route gated only by `@approver_required` has no tenant boundary by default: it must add an explicit org-membership check if it touches data that isn't already scoped by `user_id`, or any `role='approver'` account can act on every organization's data platform-wide (see CLAUDE_RUNBOOK.md, change-governance org-scope fix and its 2026-07-26 ApprovalRequest recurrence). The org-membership lookup itself is centralized in `services.rbac.user_active_org_ids(user_id)` — import it rather than reimplementing an `OrganizationMember` query; that duplication is exactly how the recurrence happened. Two visibility helpers build on it: `routes/changes.py`'s `_change_visible_to_approver(change, user)` for `InfrastructureChange` (which has its own `organization_id`, stamped at creation from the requester's active org) and `services/approval_service.is_visible_to_approver(req, approver)` for `ApprovalRequest` (which has no `organization_id` column — visibility is derived from whether the approver shares an active org with the *requester*). `_change_visible_to_approver` treats a requester with no active org membership as admin-only, since there's no team to scope against. **Agent requests (`ApprovalRequest`) no longer use the platform role alone:** organization owners/admins approve their team's, and a requester nobody else can approve confirms their own — see "Approvals: who confirms what" under Feature Reference.

### Admin Pages

| URL | Description |
|---|---|
| `/admin/` | Dashboard — user counts, role breakdown, recent signups |
| `/admin/users` | List, search, filter all users |
| `/admin/users/<id>` | View user detail, change role, lock/unlock, delete |
| `/admin/audit-log` | Usage log audit trail |

### Granting Admin Access

There is no self-serve promotion — it must be done directly in the database. On the EC2 server:

```bash
ssh -i your-key.pem ubuntu@13.222.47.92
cd /var/www/devops-agent
source venv/bin/activate
python -c "
from app import app
from models import db, User
with app.app_context():
    user = User.query.filter_by(email='you@example.com').first()
    user.role = 'admin'
    db.session.commit()
    print(f'Done — {user.email} is now admin')
"
```

Then visit `https://devopsagent.io/admin/`.

---

## Current User Context

Each user has isolated:
- Chat conversations and history
- Cloud credentials (AWS/Azure/GCP)
- Infrastructure resources
- Cost optimizations and alerts
- Subscriptions and credits
- Proactive recommendations, artifacts, skill activations

---

## Feature Reference

### Context-Aware Chat + Artifacts
**Access:** Chat page → 📄 button in header toggles Artifacts slide-out panel (right side)

**What it does:**
- Agent knows what page/resource the user is viewing via `page_context` and `resource_context` fields in the POST body
- Tool traces (every tool call made during a stream) are persisted to `ChatMessage.tool_trace`
- Generated documents (runbooks, reports, specs) can be saved as versioned `ChatArtifact` records

**URL context shortcut:** Opening `/chat?ctx=resource&type=ec2&id=i-xxx&name=web-01&action=investigate` pre-fills the chat input and sets resource context automatically. The topology map uses this — hovering a node shows "Investigate →" which opens chat with that resource.

**`?cid=<conversation_id>`** opens that specific conversation. It routes through
`loadConversation(cid)`, which hits `GET /api/conversations/<id>` — that endpoint
verifies ownership **and** sets `session['conversation_id']`, so it both renders the
history and binds the session, which is what makes anything sent next land in that
conversation. The client never sends a conversation id with a chat message; the
server resolves it from the session alone. Adding `&wf_exec=<id>` additionally
auto-sends a workflow prompt stashed in `sessionStorage` — see the Workflows note below.

**New model:** `ChatArtifact` (fields: `artifact_type`, `title`, `content`, `version`, `is_latest`, `parent_id`)
**New columns on `ChatMessage`:** `tool_trace` (JSONB), `page_context` (VARCHAR 100)

**API endpoints (`routes/artifacts.py`):**
```
GET    /api/chat/artifacts               → list artifacts (filter by conversation_id optional)
POST   /api/chat/artifacts               → create {artifact_type, title, content, conversation_id}
GET    /api/chat/artifacts/<id>          → get single artifact
PUT    /api/chat/artifacts/<id>          → create new version (increments version, flips is_latest)
DELETE /api/chat/artifacts/<id>          → soft-delete (set is_latest=False)
GET    /api/chat/artifacts/<id>/export   → download as .md file
```

---

### Drift Detection (`/drift`)

Service `services/drift_detection.py`, routes `routes/drift.py`. Reads live AWS through
`credential_service.get_user_boto_client(user_id, …)` — never ambient credentials, never
canned data (see the standing rule at the top of this file, and CLAUDE_RUNBOOK.md's
2026-08-12 entry for what happened when it did).

**Two ways to create baselines, both cloud-backed:**
- `POST /drift/api/baselines/capture` → `capture_baselines_from_account()` snapshots the
  account's current EC2 / security groups / S3 / RDS as the expected state. Optional
  `resource_types` filter.
- `POST /drift/api/import/terraform` → baselines from a `terraform.tfstate`.

**Capture and scan MUST share the `_normalize_*` helpers.** `_fetch_*` (single resource,
used by scans) and `capture_baselines_from_account` (paginated lists) both funnel through
`_normalize_ec2_instance` / `_normalize_security_group` / `_normalize_rds_instance`. If
capture wrote a different key shape than a scan reads back, every captured baseline would
report drift the instant it was created — `tests/test_drift_baseline_capture.py::
test_captured_baseline_scans_clean` is the guard.

**Semantics worth preserving:**
- A resource that genuinely doesn't exist → `_fetch_*` returns `None` → **one** REMOVED
  finding. Never let a missing resource become an empty dict; `_compare_configs` reads
  that as "every expected property was removed" (one absent RDS produced 6 findings).
- Cannot read the account → `DriftScanError`, surfaced as 502 `scan_failed`. An unreadable
  account is not a clean one and must never render as findings.
- A baseline is a **subset** of pinned properties; live properties absent from it are not
  drift. Don't reintroduce an "added property" check.

### Pre-built Workflows (`/workflows`)

Catalog in `services/starter_workflows.py` (seeded at import — see "Seeded catalogs"),
routes in `routes/workflows.py`.

**Running a workflow is a chat dispatch, and the dispatch happens in the browser.**
`POST /api/workflows/<id>/execute` creates an empty `Conversation`, a `WorkflowExecution`
with status `queued`, and returns `{conversation_id, execution_id, prompt, redirect_url}`.
It deliberately does **not** persist the prompt as a `ChatMessage`: writing a user message
row does not run the agent — only `/api/chat/stream` does — so a seeded row produces a
conversation that displays the prompt and then does nothing forever. `workflows.html`
stashes the prompt in `sessionStorage` under `wf_prompt_<execution_id>`, and the chat
page's `?cid=` handler sends it via the normal `sendMessage()` path. Keying by execution
id is load-bearing: it's what stops "View Chat" on a finished run from re-executing it.

**Execution status must never depend solely on the browser.** `completed`/`failed` are
written by the SSE `done` handler in the page, so a closed tab would strand a row at
`running` forever. `list_executions` reconciles on read: past `STALE_EXECUTION_MINUTES`
(30), an assistant reply in the conversation means `completed`, none means `timed_out`.
Any new status a client reports must have an equivalent server-derivable fallback.

**Input forms (added 2026-10-13, `services/workflow_inputs.py`).** A workflow may declare
`inputs` (field specs: `text|select|cidr|secret|number`) and reference them in its steps as
`{key}` placeholders. Run opens a short prefilled form instead of the agent asking in chat;
`execute_workflow` validates the submitted values **before** creating any row (400 with
per-field `fields` errors), fills them into the steps, and lists them in the prompt with
"do not ask me again". Rules that are load-bearing:
- Only declared `{identifier}` tokens are replaced, so literal JSON braces in steps are safe.
  Values may not contain braces, backticks or newlines (they land inside a prompt).
- `cidr` refuses `/0` unless the spec sets `allow_world` — only the two public web-app
  workflows do, and `test_workflow_inputs.py` pins that list. A `cidr` field with no default
  is prefilled from `GET /api/workflows/client-ip` (CF-Connecting-IP, global addresses only).
- `secret` left blank is generated (`secrets.token_urlsafe`). Never put a default password
  in step text — the Prometheus workflow shipped `GF_SECURITY_ADMIN_PASSWORD=admin` until this.
- `spec_problems()` (run over every starter workflow by the tests) fails on an input no step
  uses or a placeholder no input declares.

**Seeding now refreshes curated rows.** `seed_workflow_templates()` used to skip by name, so
edits to an existing starter workflow never reached production. It now also updates
`_SYNCED_FIELDS` on curated rows (`is_public` and `created_by IS NULL`); user-created
templates are never touched.

Categories as of 2026-10-13: Compute, Security, Monitoring, Storage, Database, Cost,
Networking, AI/ML, App Hosting, Kubernetes, Incident Response, IaC, CI/CD, On-Call. 46 starter
workflows across AWS, Azure, GCP, Kubernetes, GitHub, GitLab, Jenkins, SonarQube, PagerDuty
and OpsGenie. `tests/test_workflow_inputs.py` pins, per workflow:
- every tool it names exists in the live catalog;
- the read-only list (Incident Response, pod troubleshooting, IAM audit, compliance check,
  cluster health check, multi-cloud snapshot) names no write tool;
- provisioning workflows end with a teardown step;
- the fix-offering audits (public S3 buckets, idle resources) change nothing until the user
  names the items;
- the new databases (RDS, Azure SQL, Cloud SQL) are private, encrypted and firewalled to one IP.

Rules for new workflows:
- When a dedicated tool can't express a safe default, use the `*_api_write` escape hatch.
  `create_rds_instance` has no subnet group, security group, encryption or deletion-protection
  parameters, so the RDS workflow calls `aws_api_write("rds", "create_db_instance", ...)` with
  `ManageMasterUserPassword` (the password never enters chat).
- **Do not build workflows on `docker_*` or `terraform_*` tools.** They run against the DevOps
  Agent server's own Docker daemon and local filesystem, not the customer's machine or repo.
- CI/CD and On-Call workflows (added 2026-10-13) open with `_NEEDS_INTEGRATION`, which points
  at Settings > Integrations and never asks for a pasted token. Their one write (re-run, retry,
  rebuild, page) waits for "I say yes". `tests/test_workflow_inputs.py` pins both
  (`INTEGRATION_WORKFLOWS`, `CONFIRM_BEFORE_WRITE`). `get_github_run_jobs` was added for them:
  run details alone have no job, step or log data.

**Integration credentials are per user (fixed 2026-10-13).** GitHub, GitLab, Jenkins, PagerDuty,
OpsGenie, Datadog, SonarQube and Nexus tools used to fall back to the platform's env vars
(`GITHUB_TOKEN`, `PAGERDUTY_API_KEY`, `SONAR_TOKEN`, ...), so any user's chat acted through the
platform's accounts. The URL-taking ones (GitLab, Jenkins, SonarQube, Nexus) also sent that
platform secret to whatever URL the chat supplied. Now:
- Credentials live in `UserIntegrationCredential` (encrypted with the same key as
  `UserCloudCredential`, but a separate table so they never count as a cloud account, trigger a
  sync, or appear in `connected_providers`). `services/integration_credentials.py` holds the
  provider specs (`INTEGRATIONS`), validation, save/load/status, and `resolve()`.
- Tools call `src/tools/integration_auth.credentials(provider, caller_url=..., **explicit)`. It
  uses values the caller passed explicitly, otherwise the requesting user's saved row, and
  **never** env vars. With neither it raises `IntegrationNotConnected` ("connect it in Settings >
  Integrations"). A saved secret is only sent to the saved URL's origin; a different host passed
  by the chat is refused.
- The requesting user comes from `integration_auth`'s thread-local, set and cleared by
  `DevOpsAgent._set_cloud_user_context` / `_clear_cloud_user_context` with the cloud contexts.
- Settings > Integrations (`#integrations`, `routes/integrations.py`: `GET/PUT/DELETE
  /api/integrations[/<provider>]`) connects each tool. Secrets are write-only: never returned,
  and a blank secret on update keeps the saved one. URLs go through `assert_safe_url` at save.
- `tests/test_integration_credentials.py` fails if any of these tool modules mentions one of the
  old env var names again, or if any integration works for a user with nothing saved.
- The CLI (`main.py`) has no signed-in user, so these tools need explicit tokens there.
- When adding a tool for a new third-party service, add an `IntegrationSpec` and resolve through
  `credentials()`. Never read a credential from `os.environ` inside a tool.

**AI/ML workflows (added 2026-10-12, extended 2026-10-13):** five self-hosted LLM
workflows — AWS EC2, EKS, Azure GPU VM, GCP GPU VM, and on-prem Kubernetes. Steps
are prose, so `tests/test_llm_workflows.py` pins what prose can't enforce: every tool
a step names exists in the live catalog, single-VM workflows only ever open the vLLM
port to the user's CIDR (never `0.0.0.0/0`), each cloud workflow checks its GPU quota
before any launch (AWS `L-DB2E81BA`; Azure compute `usage.list`; GCP `NVIDIA_L4_GPUS` /
`GPUS_ALL_REGIONS`), the on-prem workflow never calls a cloud API or attempts host-level
installs, and every workflow ends with teardown. The Azure and GCP workflows share
`_VLLM_PIP_SETUP_LINES` (pip/uv install, vLLM as a systemd unit — idempotent, so a
driver-extension reboot or a re-run can't leave it stopped); its rendered form is
`bash -n`-checked by the test. Images, driver-extension versions and quota entries are
resolved **at run time** through `*_api_read`, never hardcoded.
**`create_virtual_machine` (Azure) is secure by default since 2026-10-13:** it used to
create a Basic dynamic public IP and a NIC with no NSG and password-only login, i.e. a VM
open to the whole internet, from a low-risk `create_` tool with no confirmation prompt.
It now always attaches an NSG, uses a Standard static public IP (closed unless an NSG rule
allows traffic), opens only `open_ports` (default 22) from one `allowed_source_cidr`,
refuses world-open sources (`0.0.0.0/0`, `*`, `Internet`, `::/0`) before creating anything —
internet exposure must go through the confirmation-gated `create_nsg_rule` — and
`ssh_public_key` disables password login. Default image moved from EOL Ubuntu 18.04 to
22.04 (`0001-com-ubuntu-server-jammy` / `22_04-lts-gen2`). Guarded by
`tests/test_azure_vm_secure_defaults.py`; the Azure LLM workflow now uses this tool. The EKS workflow pins
`nvcr.io/nvidia/k8s-device-plugin:v0.17.1` (the AL2023 NVIDIA AMI ships drivers but
not the device plugin) — bump it deliberately. **A new workflow category needs a
matching `filter-chip` in `templates/workflows.html`**; `test_workflow_seeding.py`
now reads the chips from the template and fails if they drift. Teaching notes for
this domain live in `LEARNING_MODE_CONTEXT` ("Self-hosted LLMs").

### Optimize (`/optimization`) — removed 2026-10-13

The Optimize area (`routes/optimization.py`, `templates/optimization/`,
`services/performance_optimizer.py`, `services/prevention_engine.py`) was deleted at the
owner's request. Its fabricated sample data had already been stripped by the 2026-09-20 audit
(see the real-cloud-account section above), which left the page rendering an empty list —
nothing ever fed `analyze_resource()` live data. Real cost data lives elsewhere and is
unaffected: `services/cost_explorer.py` backs `/api/dashboard/costs` and the
`get_cost_summary`/`get_optimization_recommendations` agent tools. Slack/Teams cost, security,
and change notifications now link to `/dashboard`. The `ProactiveRecommendation` table is left
in place, unused. `tests/test_optimize_removed.py` guards against a dangling link or a
`url_for('optimization.…')` (one in `scaling/dashboard.html` would otherwise 500 `/scaling`).

### Monitoring (`/monitoring`) — removed 2026-10-13

The Monitoring page (`routes/monitoring.py`, `templates/monitoring/`) and the engine behind it
(`services/proactive_monitoring.py`) were deleted at the owner's request. That engine seeded
default alert rules for every user with a cloud account, evaluated them on a 60s scheduler tick
(`monitoring_tick`, also removed from `services/scheduler.py`), and **auto-opened incidents** and
sent Slack/Teams/status-page notifications when an alert fired. **Incidents are no longer created
from metric alerts**. (Incidents themselves were removed later that day; see below.) ChatOps
`/alerts` and `/metrics` were removed. The dead `notification_service.notify_alert()` (it linked to `/monitoring`) was deleted;
`status_service.broadcast_incident()` is now unused but kept. The agent's Prometheus/Datadog/Grafana
tools (`src/tools/monitoring_tools.py`) are a separate feature and remain. `MonitoringRuleModel` /
`MonitoringAlertModel` tables are left in place, unused. `tests/test_monitoring_removed.py` guards
the route, the engine import, the scheduler tick, the ChatOps commands, and every page that used to
`url_for('monitoring.…')` (six did — each would 500 without the fix).

### Incidents (`/incidents`) and Analysis (`/analysis`) — removed 2026-10-13

Removed at the owner's request, the same day as Monitoring and with nothing left feeding them
(Monitoring had been the main source of incidents). Deleted: `routes/incidents.py`,
`services/incident_response.py` (incidents, playbooks, correlation groups, investigation journal),
`routes/analysis.py`, `services/root_cause_analyzer.py`, `templates/incidents/`,
`templates/analysis/`, and the unused old `templates/dashboard.html`. Also removed because they
only read or wrote incidents:
- ChatOps `/status`, `/incidents`, `/incident`, `/ack`, `/resolve`, `/playbooks`, `/execute`,
  `/analyze`. What's left is `/help`, `/deployments` (admins), `/oncall` and `/link`.
- The developer API's `/api-gateway/v1/incidents` GET/POST (already broken: they imported a
  nonexistent `models.Incident`) and the `incident.created`/`incident.resolved` webhook events.
- The public `/status` page's incident list. It queried every user's incidents with no
  `user_id` filter, onto an unauthenticated page. Health checks and subscriptions stay.
- CI/CD webhook failures no longer create incidents (`_handle_failure_event`, and the
  `app_user_id` argument it needed on `process_webhook`).
- `notify_incident()` / `send_incident_notification()` and the Incidents notification toggle
  (the `notify_incidents` column and API field are kept, unused).
- Incident counts in the health score, Analytics dashboard (`/analytics/api/alerts/summary`,
  `/analytics/api/incidents/stats`) and the weekly digest email.

Kept: the agent's PagerDuty/OpsGenie tools, the "Incident Response" workflows (chat
diagnostics), the `incident_runbooks` skill, and `CrisisIncident` (guardrail crisis logging,
unrelated). The `incidents`, `playbooks` and `incident_correlation_groups` tables stay in place,
unused. `tests/test_incidents_removed.py` guards the routes, modules, ChatOps commands, API
endpoints and every page that linked to them.

---

### 2026-10-14 app audit

A full audit (Keep / Fix / Remove per area, with evidence) was written up for the owner and is
being worked through in eight steps. Step 1 done: the developer API's resource endpoints read
fields `InfrastructureResource` doesn't have (`name`/`provider`/`metadata`) and returned 500 for
anyone with a synced resource; they now go through `routes/api_gateway._resource_json()`, and the
missing `/api-gateway/api/webhooks` JSON list the developer pages call was added.
**InfrastructureResource's fields are `resource_name`, `cloud_provider`, `resource_metadata`** —
there are no `name`/`provider`/`metadata` aliases (and `.metadata` is SQLAlchemy's MetaData).

Step 2 done: public pages and plan features only promise what the app does. The plan list
(`TIER_DEFINITIONS`) now lives once, in `services/subscription_tiers.py`; `/init-database` and the
`__main__` block call `upsert_all_tiers()`, and an import-time `sync_tier_features()` (under
`seed_lock`) refreshes **only `features` and `description`** on existing rows, so a deploy can never
change what anyone pays. `tests/test_public_claims.py` holds the banned-phrase list (SOC 2/HIPAA,
resource/team-member limits, auto-remediation, the 23% figure, HMAC webhooks, Monitoring & Alerts)
for landing, About, Docs, chat and every plan; add a phrase there when a feature is removed.

Step 3 done: **Compliance is gone** (`routes/compliance.py`, `services/compliance_service.py`,
`services/pdf_service.py`, `tasks/security_tasks.py`, its templates). Its SOC 2 scored 100% with no
AWS account and "Add evidence" did nothing. In its place the Dashboard has **Security checks**
backed by `services/security_scanner.py`: `scan_aws_security()` runs S3 / security-group / RDS /
IAM checks through the user's own credentials, records per-area `checks` (`ok`/`error`), raises
`SecurityScanError` when no area could be read (route returns 502 `scan_failed`, never "clean"),
de-duplicates and upserts `SecurityFinding` rows, and auto-resolves findings a successful check no
longer sees. Routes: `GET /api/security/summary`, `POST /api/security/scan`,
`POST /api/security/findings/<id>/dismiss` (user-scoped, else 404). The agent's
`run_compliance_check` tool now lists related controls without a score and says it is not a
compliance assessment; the system prompt forbids claiming SOC 2/HIPAA/PCI compliance.

Step 4 done: pages that did nothing for customers were removed: `/notifications` (saved Slack/
Teams settings in per-process memory that real alerts never read; channels live in Settings →
Notifications, `UserNotificationChannel`), `/teams` (staff user list; teams are Organizations),
`/templates` (saved prompts, linked from nowhere), Admin › System settings (fixed "Connected"
badges), ChatOps (`routes/chatops.py`, `services/chatops_service.py`), the inbound CI webhook
receivers (`routes/webhooks.py`, one server-wide secret, fed nothing), AI Deployments /
Recommendations / Optimize, Analytics › Performance, and `services/audit_service.py` /
`services/websocket_service.py`. `NotificationService` (the in-memory store) is gone; change
requests now notify through `notify_change_event()` → `_send_async()`, so they are actually
delivered. Guard: `tests/test_shell_pages_removed.py` (routes 404, modules unimportable, no page
links to them).

Step 5 done: the Dashboard only shows what it can back up. In
`services/infrastructure_sync.py`: idle-instance recommendations need CloudWatch CPU (no
name-based fallback) and Spot recommendations (pure name guesses) are gone; "stopped for N days"
reads `resource_metadata['stopped_since']`, parsed from EC2's `StateTransitionReason` (it used
`last_synced`, which every sync resets, so it never fired); EC2 sync is paginated; each run deletes
pending recommendations it no longer supports (thread-local `_seen_this_run()`), never recreates a
dismissed one, and tells account-level rows apart by title (every unattached volume used to
overwrite one row). `services/cost_explorer.get_actual_costs()` merges a service across the two
months a 30-day window spans and returns `source: 'cost_explorer'`; the DB fallback in
`/api/dashboard/costs` returns `source: 'estimate'` and **no forecast** (it was the estimate ×
1.05). The page labels estimates; "Apply" (always 501) is replaced by **Fix in chat**, which opens
`/chat?prefill=<text>` (filled in, not sent). Guard: `tests/test_dashboard_honest.py`.

Step 6 done: alerts that were promised now go out.
- **Outgoing webhooks** (`services/api_gateway.dispatch_webhook_event`): `resource.created` /
  `resource.deleted` are sent from `DevOpsAgent._audit_infrastructure_change` (so from chat and
  approved requests; direct `/execute`, `/api/v1/tools/execute` and MCP calls without an approval
  step write no change row and send nothing yet), and `cost.threshold` from budget alerts. Only
  `DELIVERED_EVENTS` are offered; resource.updated / alert.triggered / deployment.* were offered
  and never sent. Delivery runs on a daemon thread with its own app context; one SSRF-blocked
  endpoint no longer stops delivery to the rest; the body is the exact signed bytes
  (`json.dumps(payload, sort_keys=True)`), so `X-DevOps-Agent-Signature` verifies against the raw body.
- **Teams** channels now receive `_send_async` notifications (only Slack did).
- **Budget alerts** (`services/budget_alerts.py`): `check_user_budgets()` runs from the
  scheduler's hourly `budget_check`, each alert at most daily (`BudgetAlert.last_checked_at`),
  reading billed spend from Cost Explorer (monthly = month to date, weekly = Monday to date,
  daily = yesterday). Over budget → email + channel message + webhook, once per period.
  `BudgetCheckError` (billing unreadable) leaves the alert unchecked, never "under budget".
- **Weekly digest** runs hourly and sends on Sundays once per user (`User.last_digest_sent_at`);
  it ran every 168h from process start and almost never fired. It honours `User.email_opt_out`
  and links the signed `/email/unsubscribe` (which now covers onboarding and digest emails).
- The scheduler's `cost_check` / `security_scan` jobs (log-only, matched nobody) are gone.
Guard: `tests/test_real_alerts.py`.

Step 7 done: the public `/status` page probes what it reports (`services/status_service.py`):
database `SELECT 1`; Kimi and Claude `GET /v1/models`; Stripe `GET /v1/balance`; Brevo
`/v3/account`, SendGrid `/v3/scopes` or an SMTP `NOOP`. Results are cached `CACHE_SECONDS`
(120) under a lock so the public page can't hammer providers; public `detail` text is a fixed
phrase, never exception text. The page shows the server's check time (`checked_at`), and
`/api/status/health` returns it. The "Get notified" sign-up (`/api/status/subscribe`,
`/status/confirm`) is gone because nothing emailed subscribers; `/status/unsubscribe/<token>` still
works for old links. Deploy health checks use `/health`, not this endpoint. Guard:
`tests/test_status_page_real.py`.

Step 8 done (agreed with the owner first):
- **One approval queue.** Change requests (`InfrastructureChange`) use the agent-request rules:
  `approval_service.can_review_change()` / `can_confirm_own_change()` wrap `can_approve()` /
  `can_self_confirm()` with the change's `user_id` as requester, and `reviewable_requester_ids()`
  scopes lists. Visibility now follows the **requester's** organizations, not the
  `organization_id` stamped from the session. `/api/changes/<id>/approve` doubles as "confirm my
  own"; `/reject` is also the requester's cancel. `/approvals` and `/approvals/mine` show both
  kinds; `/changes` is history plus execute/rollback, and its pending rows link to Approvals.
  `@approver_required` is no longer used in `routes/changes.py`. The page's summary cards each
  fetch their own unfiltered count (the Total card once showed the filtered list's size), and the
  empty Pending tab points to `/approvals`, where chat requests wait (`tests/test_changes_page_stats.py`). Guards:
  `tests/test_change_approvals_unified.py` and the updated org-scope tests.
- **One developer API.** `/api-gateway/v1` serves everything `/api/v1` offered via
  `routes/api_gateway.V1_PARITY_ROUTES` (same handlers and `api_key_service.require_api_key`, so
  scopes, IP allow-lists and the daily limit behave identically; don't also wrap them in the
  gateway's `api_key_required`, which would count each request twice). `GET /v1/openapi.json` is
  generated from the live URL map (the old `/api/v1` spec had empty `paths`). `/api/v1` responses
  carry `Deprecation`, `Sunset` (`API_V1_SUNSET`, default 2027-01-12) and a successor `Link`.
  **Removing `/api/v1` is a separate change on or after that date.** Guard:
  `tests/test_one_developer_api.py`.

### 2026-10-22 code review fixes

A full read-only review found five issues the owner asked to fix first (CLAUDE_RUNBOOK.md has the detail):
- **SSO trusts an IdP only for its org's verified domains.** `sso_service.find_or_provision_user()` refuses
  an email whose domain is not a DNS-verified `OrganizationDomain` of that org
  (`email_domain_verified_for_org`), and a user already linked to another org. Any signed-in user can
  create an org and point it at their own IdP, so without this an asserted `admin@...` logged in as that
  admin. String claims like `email_verified: "false"` are false (`_claim_true`).
- **Host-local tools are off on the hosted site.** `command_tools`, `git_tools`, `docker_tools`,
  `terraform_tools` and `ansible_tools` act on this server, so they register (chat agent and MCP) only
  with `DEVOPS_AGENT_HOST_TOOLS=true` (`src/tools/host_local.py`); the CLI keeps them. `execute_command`
  resolves its program on PATH and refuses any path (`/tmp/x/ls` passed the old basename check).
  `/api/sandbox/run` is admin-only, needs the same flag, and never has network. Guard:
  `tests/test_host_local_tools.py`.
- **Approved results are stored redacted.** `approval_service.stored_result()` writes a redacted copy to
  `ApprovalRequest.execution_result` and the chat; a key file, or the whole result of a
  `secret_detector.SECRET_DISCLOSING_TOOLS` tool, is kept Fernet-encrypted in `download_payload` for the
  requester to download once within `DOWNLOAD_TTL_MINUTES` (60) via `/api/approvals/<id>/download`
  (the chat card and /approvals/mine show the link). `to_dict()` redacts `tool_input` and
  `execution_result` for reviewers. `InfrastructureChange.execution_result` goes through
  `core._stored_change_result()`. The developer API's synchronous confirm still returns the raw result to
  the key's owner (`return_raw`). `secret_detector` now redacts whole PEM blocks, JSON-quoted labels, and
  never splices overlapping matches; use `redact_structure()` for dicts. Guard:
  `tests/test_approval_result_redaction.py`.
- **`check-errors.yml` no longer prints the database password or full emails.**
- **API keys: scopes, IP allow-list, header only.** `/api-gateway/v1` routes declare a capability
  (`@api_key_required('read'|'agent'|'execute')`), checked by `api_key_service.key_grants()` /
  `key_ip_allowed()`: `read` reads, `agent` (Settings' default) chats and runs tools, `write` runs tools,
  `admin` everything. MCP API keys need `execute`. `?api_key=` is refused. Guard:
  `tests/test_api_key_scopes.py`.

2026-10-29 scheduled review: `_is_safe_redirect` now rejects scheme-without-host (`http:/evil.com`), backslashes and control characters; `/api/run-migration` is admin-only. Guard: `tests/test_safe_redirect.py`.

Still open from that review (not fixed): org invitations join on GET and aren't bound to an email; TOTP
setup marks the email verified; login messages reveal which
accounts exist; MCP OAuth doesn't require PKCE; sandbox mode is ignored on `api/v1` and `/v1/agent`;
`terraform_apply(plan_file='-destroy')`; `query_bigquery` unclassified; `*_api_read` can read secret
values; stored XSS in Settings > Learning and the map's `esc()`.

### Known gaps found by the 2026-10-14 docs audit (not yet fixed)

- **`docker-compose.yml`'s `app` service has `build: .` but there is no Dockerfile.**

### AI Infrastructure box fixed; Predictive Scaling removed (2026-10-14)

- **`/ai/api/parse`** used to call `parse_natural_language`, which `AIInfrastructureService`
  never had, and the pages sent `query` while the route required `request`, so the box always
  failed. It now accepts either field, runs `parse_request()` + `generate_spec()`, and returns
  `{intent, spec, terraform, note}`. It **only generates code**; nothing is created. AWS only
  (`SUPPORTED_PROVIDERS`); Azure/GCP or unrecognised text → 422 with a pointer to Chat.
- **The generated Terraform is safe by construction:** EC2 uses a `data "aws_ami"` lookup pinned
  to Canonical's owner `099720109477` (same id as `aws_tools._AMI_OWNERS`), never a literal AMI
  (it used to hardcode `ami-0c55b159cbfafe1f0`); IMDSv2 required; RDS uses
  `manage_master_user_password`, private, encrypted, deletion protection, final snapshot; S3 gets a
  public-access block. ALB is a comment (needs the user's subnets).
- **No invented prices.** `estimated_cost` and the hardcoded per-size dollar table are gone.
- `parse_request` now collects **every** resource in a request (`intent['actions']`), via
  `CREATE_VERBS` + `RESOURCE_NOUNS`, so "create 3 small servers and a database" yields both.
- Removed endpoints that called nonexistent methods: generate-terraform, generate-cloudformation,
  estimate-cost, validate, deploy, explain, convert, security-scan; plus `/ai/api/analyze-drift`,
  which reported "No drift detected" without reading any account (real drift is `/drift`).
  `AIInfrastructureService.execute_request()` (logged "All resources provisioned successfully"
  with no cloud call; no callers) was deleted.
- **Predictive Scaling** (`routes/scaling.py`, `services/predictive_scaling.py`,
  `templates/scaling/`) was removed at the owner's request: nothing ever called `add_metric()`,
  so it was always empty. It had no DB tables. Guard: `tests/test_ai_box_and_scaling_removed.py`.

### Approvals: who confirms what (2026-10-14)

`services/approval_service.py`. A medium/high-risk call from a `role='user'` account (chat on
all three model paths, and the MCP connector) files an `ApprovalRequest`. Then:
- **Who can approve** is `eligible_approver_ids(req)`: active members of any organization the
  requester belongs to whose `OrganizationMember.role` is `owner`/`admin`, **or** whose platform
  `User.role` is `approver`/`admin`; never the requester. `can_approve(req, user)` adds platform
  admins (who see everything, for support). Org owners/admins were added 2026-10-14: before,
  only the platform `approver` role counted, and only platform admins can grant it, so a
  customer team couldn't set up its own reviewers.
- **Nobody eligible** (`can_self_confirm(req)`: a solo account, or an org whose only owner/admin
  is the requester): the requester confirms it themselves via
  `POST /api/approvals/<id>/confirm` (chat card buttons, or `/approvals/mine`). Platform admins
  are deliberately not counted as eligible here and are **not** emailed: they can't judge a
  customer's account, and before this such requests just expired.
- The requester cannot approve their own when someone else is eligible, but can always cancel
  (`/cancel`, stored as `rejected` with `approver_id == requester_id`).
- **Approvers and admins** (platform role) no longer run everything instantly:
  `needs_approval(user, risk_level)` lets them run **medium** risk directly, but their
  **high/critical** calls file a request that only they confirm (`can_self_confirm` is true when
  the requester is an approver/admin, and `can_approve` returns False for everyone else,
  platform admins included). All four gates (3 in `core.py`, MCP) call `needs_approval`;
  `tests/test_approval_consistency.py` fails if a raw role check comes back.
- **Both direct-execution APIs use the same rules** via `gate_api_call()`:
  `/api-gateway/v1/execute` and `/api/v1/tools/execute`. First call → 202 + `approval_id`;
  re-sending the identical call with `approval_id` confirms it when `can_self_confirm`, else
  reports status/result. The confirmed run goes through `_execute_tool` (verified, audited,
  cache-invalidated). The developer API's stateless HMAC `confirm_token` and `/api/v1`'s
  `"confirm": true` were removed: both let any key holder skip approval. The developer API also
  now **fails closed (503)** when `SafetyValidator` raises; it used to run the tool unchecked.
- `routes/approvals.py` gates the queue/history/approve/reject on `_reviewer_required`
  (platform approver/admin **or** owner/admin of any org), not `rbac.approver_required`.
  Non-reviewers hitting `/approvals` are redirected to `/approvals/mine`. Org owners/admins see
  **agent requests only**: change requests (`InfrastructureChange`) are still approved through
  `/changes`, which keeps `@approver_required`, so `_org_scoped_change_query` returns nothing
  for them. History is scoped by `_reviewable_requester_ids()`.
- `waiting_message(req)` is the tool-result text the model sees; it says which of the two
  applies, so the agent tells the user the right next step.
- **The gate fails closed.** If filing the request raises (or the user row is missing), the
  Claude path and MCP now block the call. Both used to log a warning and run it anyway. The two
  Kimi paths already failed closed. A path with **no** user id at all (the CLI) still runs
  risky tools unconfirmed, as before.
- `approve()` and `confirm_own()` share `_run_approved()`. `_execute_tool()` now invalidates
  the requester's `READ_CACHE` (on success and on a raised tool), which it skipped because it
  calls the handler directly rather than through `_invoke_tool`.
- `/setup` (writes the platform Anthropic key into `config/.env` and re-initializes the shared
  agent) is `@admin_required`; it was `@login_required` only. `/doctor` (platform diagnostics)
  is admin-only too, and no longer prints the first 12 characters of the Anthropic key.
- Pinned by `tests/test_approval_self_confirm.py`, `tests/test_org_admin_approvals.py` and
`tests/test_approval_consistency.py`.
- **Finding and confirming a waiting request (2026-10-17).** Kimi chats use the non-streaming
  `/api/chat`, which never sent the approval card, so users were told to "click the button in
  chat" with no button. Requests filed there (and `_pending_approval` from the Claude gate or an
  AWS permission request) are collected in the greenlet-local `_filed_approvals`, returned as
  `approvals` in the response, and drawn by `renderApprovalCard()` in `index.html` (shared with
  the streaming `approval_required` event). Also: `create_request()` returns an identical pending
  request instead of filing a copy (typing "approve" made the model re-call the tool); the
  Approvals link and `/api/approvals/count` are for every signed-in user and count their own
  self-confirmable requests too; `/approvals` shows "Waiting for your confirmation" above the
  queue (`static/js/my_requests.js`, shared with `/approvals/mine`), because an admin's own
  requests never appeared there; bell notifications use `data-notif-*` attributes (the inline
  `onclick` with a quoted link was a syntax error, so none were clickable); and
  `_approval_status_context()` puts the user's last 24 hours of requests with their real status
  into the prompt, after the agent claimed requests were approved and then "flipped back".
  `build_risk_reason()` names the call for the `*_api_write` escape hatches ("This will call
  iam create_role: RoleName=..."); they used to read only "This will execute: aws api write".
  Guard: `tests/test_approval_chat_visibility.py`.

- **Confirm/approve from a web page runs in the background (2026-10-19).** `/api/approvals/<id>/confirm`
  and `/approve` call `confirm_own`/`approve` with `background=True`: `_claim()` moves the row
  pending -> approved in one conditional UPDATE (two clicks can never run it twice), the route
  returns `{status: 'running'}` at once, and `_finish_run()` executes on a daemon thread that
  re-enters the app context and re-queries by id. It used to run the tool inside the HTTP request,
  so a long call (an EKS create, a ~57s delete read-back) hit Cloudflare's ~100s limit: the browser
  showed an error, a second click said "already approved", and the chat card stopped polling on
  `approved` and stayed on "Running" forever. Now the card (`renderApprovalCard`) and
  `/approvals/mine` treat `approved` as running with elapsed time; a lost POST reply checks the
  status before offering the buttons again. `/status` returns `running` and a plain `summary`
  (`summarize_result()`); the result saved to the chat starts with that sentence, JSON below as
  Details. When the run finishes, `continueAfterApproval()` sends "The approved action has
  finished... continue" so the agent picks the task back up; it shows a Continue button instead
  if a reply is streaming or the user is typing. A row left `approved` for `RUN_STALE_MINUTES`
  (30, e.g. a restart killed the thread) becomes `executed` with `INTERRUPTED_RESULT`, which says
  it may or may not have run. `gate_api_call` (developer APIs) stays synchronous. Tests run jobs
  inline via the autouse `_approval_runs_inline` fixture in `tests/conftest.py`. Guard:
  `tests/test_approval_background_run.py`.

Still open: the CLI (no
signed-in user) runs risky tools unconfirmed; an approver's medium-risk call through either API
runs directly without verification/audit (it skips the approval service).

### AWS permission requests (2026-10-15)

Owner request: when AWS refuses an action for a missing permission, write the needed
policy and ask the account owner yes/no, then retry. `services/aws_permissions.py`.
- **Trigger:** `DevOpsAgent._invoke_tool` (all 5 exec sites) passes every result through
  `_maybe_request_aws_permission`: AWS tools only (category `aws*` or `aws_api_*`), never in
  sandbox or without a user, never raises. `parse_denial()` reads the action from AWS's
  "is not authorized to perform: svc:Action" text, else builds it from "when calling the X
  operation" plus the category / `aws_api_*` `service` (boto3 client → IAM prefix and S3
  operation → IAM action maps). An explicit deny (SCP/boundary) is never proposed.
- **Request:** an ordinary high-risk `ApprovalRequest` with `tool_name='grant_aws_permission'`
  (`PERMISSION_TOOL`), deduped per pending action. That name is **never a registered tool**:
  only a real AccessDenied creates one (test pins it). The model gets `_permission_request`
  in the result; the chat card comes from `_pending_approval` (Claude path, and a check after
  each Kimi streaming tool result; Kimi non-streaming relies on `/approvals/mine`). The card
  and approvals pages show the policy, console path and CLI.
- **Approval:** same rules as any agent request (org owners/admins, or self-confirm).
  `approval_service._execute_tool` routes `PERMISSION_TOOL` to `execute_grant()`.
- **Modes:** `manual` (default): the owner adds the policy, confirms, the agent retries.
  `self` (opt-in): role-ARN connections with `self_grant` on (`set_aws_self_grant`, `PUT
  /api/aws/self-grant`, refuses unless the role has a permissions boundary; re-saving AWS
  credentials turns it off). The agent merges the statement into its own inline policy
  `DevOpsAgentGrantedPermissions`. The setting is re-read at execution, and
  `is_sensitive()` actions (iam/sts/organizations/kms/sso..., secret values, wildcards)
  are never self-granted.
- **Read bundles:** a refused read (`List`/`Describe`/`Get`/`BatchGet`) also asks for that
  service's `List*` and `Describe*` (`_READ_WILDCARDS`), so one yes covers it. Those two
  wildcards are the only ones `is_sensitive()` accepts; identity prefixes never get bundles.
- **Retry:** up to 3 tries (`RETRY_DELAYS`, IAM propagation). A different denied action on
  retry files a follow-up request (`next_permission_request`).
- **Access-level hint (2026-10-19):** from the second distinct *write* permission a user is
  refused within 6 hours, `access_level_hint()` adds `access_level_hint` to the model's note,
  telling it to suggest switching the stack to `PolicyLevel=Manage` once instead of filing
  more one-off requests (an EKS cluster on a Read role took seven).
- **CloudFormation:** `AllowSelfGrant` (default `No`) adds `DevOpsAgentSelfGrant`
  (Put/DeleteRolePolicy on its own role; deny boundary/trust/attach changes) and the
  `DevOpsAgentBoundary` managed policy as the permissions boundary (all services except
  iam/sts/organizations/account/SSO, plus IAM read, PassRole to services, own-inline edits;
  deny secret values). **After merging, re-upload `cloudformation/devops-agent-role.json`
  to S3** (`docs/iam-policies.md`); the live quick-create link serves the old template until then.
  The update-stack commands deliberately omit `AllowSelfGrant` (UsePreviousValue fails on
  stacks made before it existed; omitting resets to the safe `No`).
- Tests: `tests/test_aws_permission_requests.py`, `tests/test_iam_policies.py`.

### Signup source and sandbox-first onboarding (2026-10-15)

Owner context: no users yet; TikTok ads started 2026-10-14 (~5,000 reach). Two changes:
- **Where signups come from.** `services/signup_source.py`: an `app.py` before-request hook
  (`_remember_signup_source`, logged-out GETs only) keeps the first visit's `utm_source`/`ref`/
  `src` (+ `utm_campaign`) or else the referring site (`site:<host>`) in the session; signup
  saves it to `User.signup_source`. First visit wins. The admin dashboard shows a 30-day funnel
  (`signup_report`: signed up → verified email → finished setup → connected cloud / sandbox →
  sent a message; admin accounts excluded), signups by source, and per-user progress under each
  recent user (`user_progress`), visible on a phone without scrolling sideways. Ads and bio
  links should use `https://devopsagent.io/?utm_source=tiktok&utm_campaign=<name>`.
- **Sandbox first.** The onboarding welcome's primary button is now "Try it now — no cloud
  account needed" (`startSandbox()`); connecting a cloud account is the secondary choice.
- Guard: `tests/test_signup_source_and_sandbox_first.py`.

### npm package `@devopsagent/mcp-server` (`mcp/`)

A ~85-line stdio bridge (`mcp/bin/server.js`) that forwards JSON-RPC to
`https://devopsagent.io/mcp/` with the user's `DEVOPSAGENT_API_KEY`. **Server-side changes reach
npm users without a release**; publish only when the bridge or its docs change. Keep the version
the same in `mcp/package.json`, both places in `mcp/server.json` and `SERVER_VERSION` in
`routes/mcp.py`, with a `mcp/CHANGELOG.md` entry (`tests/test_mcp_package_version.py`). The tool
count in its docs is the MCP subset (`MCP_MODULES` in `tests/test_tool_counts.py`), not the
platform total. Publishing needs the owner's npm login (`npm publish --access public` from
`mcp/`); this repo has no npm token or publish workflow. MCP calls run tools directly, so AWS
permission requests (chat only) don't happen there.

**Connectors Directory listing.** Submit through the developer portal at
`claude.ai/directory/manage` (**MCP connector**); the old Google Forms are closed. The portal
requires every tool to have a `title` and a `readOnlyHint`/`destructiveHint`: `_to_mcp_tool()`
sets `title` on the tool and in `annotations` (`_tool_title()` turns `get_ec2_instances` into
"Get EC2 Instances"; add acronyms to `_TITLE_WORDS`). Guard: `tests/test_mcp_tool_titles.py`.
Read-only hints come from name prefixes plus whole-segment suffixes (`_list`, `_status`...); a
plain substring test once marked `create_listener` read-only.
**Every tool sets all four hints explicitly (2026-10-23).** Reviews reject a connector over an
unset hint or one that doesn't match the tool. Until then only high-risk tools were
`destructiveHint: true`, so ~200 medium-risk tools that overwrite or remove settings
(`put_iam_inline_policy`, `revoke_security_group_ingress`, `update_cloudformation_stack`) said
false, and none set `idempotentHint` (reported by an outside vendor's sales email). Now
`_get_tool_annotations()`: destructive = safety.py risk medium or above, or a `manage_*` tool;
read-only = a read by name (`_READ_ONLY_PREFIXES` / `_READ_ONLY_SECOND_WORDS` / `_READ_ONLY_NAMES`)
and not destructive; idempotent = read-only or `put_`/`set_`/`tag_`; openWorld always true.
`tests/test_mcp_tool_titles.py` checks every hint on every tool.
Directory policy also bars tool descriptions from instructing the model about other tools or its
own behaviour. The chat descriptions do that on purpose (find_ami before create_ec2_instance), so
the connector serves plain versions from `_MCP_DESCRIPTIONS` in `routes/mcp.py`; a new
description that names another tool fails `test_descriptions_do_not_steer_the_model`.
Field answers and the reviewer test-account notes are in `mcp/CONNECTOR_SUBMISSION.md`.

### Documentation layout

User docs live in `docs/` (index: `docs/README.md`): `QUICK_START.md`,
`WEB_APPLICATION_GUIDE.md`, `FEATURE_REFERENCE.md`, `API_REFERENCE.md`, `AUTOMATION_COOKBOOK.md`
and the CLI guide `USER_GUIDE.md`. The root `QUICK_START.md` and `USER_GUIDE.md` are pointers
only. `docs/archive/`, `docs/superpowers/`, `docs/designs/` and `docs/blog/` are historical and
not maintained. When a feature is added or removed, update those six guides plus the in-app
`templates/docs.html`; `tests/test_tool_counts.py` checks tool totals in templates, `README.md`,
`docs/FEATURE_REFERENCE.md` and `MCP_REGISTRY_SUBMISSION.md`.
The public `/docs` page was rewritten on 2026-10-16 (it promised env-var setup, invented Jenkins/GitHub
tool names, a Proficiency Radar and a sandbox banner, and printed the MCP OAuth client secret).
It must not show that secret, and every tool name inside `<code>` on it must exist
(`tests/test_doc_tool_names.py`). Docker, Terraform and Ansible run on the DevOps Agent host, so the
page says they're for self-hosted installs; Kubernetes reaches the user's EKS clusters (2026-10-17).

### Skills System
**Access:** Settings → Skills tab (`templates/settings/_skills_panel.html`; the old `/settings/skills` URL redirects there) — toggle built-in skills on/off, view learned infrastructure summary

**What it does:** Injects domain expertise into the agent's system prompt when the user's message contains a trigger keyword. "Learned Skills" auto-generates a summary from your synced `InfrastructureResource` records so the agent always knows what you have deployed.

**New model:** `UserSkillActivation`

**Built-in skills (`skills/*.md`):**

| File | Triggers | Content |
|---|---|---|
| `aws_cost_optimization.md` | cost, billing, savings, reserved, rightsizing | AWS rightsizing, RIs, Savings Plans |
| `kubernetes_troubleshooting.md` | pod, deployment, crashloop, kubectl, namespace | Pod lifecycle, events, resource limits |
| `security_hardening.md` | security, iam, encryption, compliance, cis | CIS benchmarks, IAM least-privilege |
| `incident_runbooks.md` | incident, runbook, postmortem, oncall | Structured incident response templates |
| `terraform_best_practices.md` | terraform, tf, module, state, drift | Module design, state management |

**Skill file format (`skills/<id>.md`):**
```markdown
---
id: kubernetes-troubleshooting
name: Kubernetes Troubleshooting
triggers: [pod, deployment, crashloop, kubectl]
compatible_providers: [kubernetes]
---
# Content injected into system prompt when triggered
```

**API endpoints (`routes/skills.py`):**
```
GET    /api/skills                       → list all skills with activation status for user
POST   /api/skills/<id>/activate         → enable skill
DELETE /api/skills/<id>/activate         → disable skill
GET    /api/skills/learned               → return learned infrastructure summary text
POST   /api/skills/refresh-learned       → regenerate from latest infrastructure sync
```

**Service (`services/skills_engine.py`):**
- `load_skills_from_disk(skills_dir)` — classmethod, called at app startup, caches parsed skills by id
- `get_active_skills_context(user_id, message)` — trigger-matches active skills; appends learned infra summary; caps at ~1500 tokens
- `generate_learned_skills_context(user_id)` — pure SQL GROUP BY resource_type, no AI call

**Tool names in skill files must be real.** Skills are injected into the agent's prompt, so a
made-up name (`list_pods`, `list_nodes`, `list_incidents`, until 2026-10-16) sends the model
after a tool it can't call. `tests/test_doc_tool_names.py` checks every backticked tool name in
`skills/*.md` and `mcp/CONNECTOR_SUBMISSION.md` against the catalog.

---

### App Shell — `templates/base.html`
All logged-in pages MUST extend `templates/base.html` (unified branded header with
Font Awesome icon nav + active states, profile menu (with the Light/Dark row), mobile nav, shared
card/btn/badge/form components, Syne/IBM Plex Mono/Outfit type system). Pattern:
`{% extends "base.html" %}` + `{% block title %}` + `{% block content %}` with
page-specific `<style>` inside the content block. Do NOT build bespoke headers or
load other fonts (JetBrains Mono/Comfortaa are legacy — replace on sight).
Migrated 2026-07-16: `dashboard_live.html`, `incidents/dashboard.html` (since removed),
`optimization/prevention.html`, `settings.html` (hash-tab sections, see "Settings in one
place" below),
`infrastructure/map.html`. Full-bleed pages (canvas/app-frame) override
`{% block main %}` instead of `content` — base wraps `.main-content` in that
block; see map.html for the pattern (flex column shell, `flex:1` viewport).
`infrastructure/map.html`'s viewport is a **natively scrolling** pan/zoom canvas,
not a transform-translate one: `#mapArea` (`flex:1`, non-scrolling frame) holds
`#viewport` (`overflow:auto`, the scroller) → `#canvas` (sizer, box = *scaled*
content size, which is what gives the scrollbars their range) → `#world`
(unscaled coordinates, `transform: scale()`). Pan writes `scrollLeft/scrollTop`;
zoom rescales `#world` and resizes `#canvas`. **Overlays (`#statsBar`,
`#legend`, `#emptyState`) must stay siblings of `#viewport` inside `#mapArea`** —
an `position:absolute` child of a scrolling container scrolls with its content,
so moving them inside `#viewport` would make the legend and stats slide off
screen. Plain wheel scrolls natively; ctrl/⌘+wheel zooms.
`index.html` (chat) keeps its own app-frame layout but its header nav and icons
are aligned with the shell. Full audit + PR sequence:
`vault/architecture/ui-rebuild-plan-2026-07.md`.
Theme switch (2026-10-16, owner request: "put it somewhere it doesn't disturb anything"):
signed-in pages have a **Theme: Light / Dark** row in the profile menu (base.html
`#accountMenuList` and the chat page's `#mainMenu`, both marked `data-theme-menu`, buttons
`.theme-choice-btn`). Neither header has a toggle any more. `static/js/theme.js` handles
`.theme-toggle-btn` and `.theme-choice-btn` with one delegated click handler and injects a
floating switch only when the page has neither a `.theme-toggle` nor a `[data-theme-menu]`; that
leftover switch (`.theme-toggle-floating`, on pages with their own header such as Billing, Changes,
Admin, Learn and the sign-in pages) is small and sits in the bottom-left corner. It used to float at
top-right, over page content. Guard: `tests/test_theme_toggle_placement.py`.

### Settings in one place (2026-10-16, owner request)
Settings is reached from the **profile icon** (base.html `#accountMenu`: Settings, Billing & credits,
Teams, Log out; the chat page's profile menu has one Settings entry). It is **not** a top-bar tab.
`/settings` tabs: Profile, Security (two-factor), Cloud Credentials, Integrations, Notifications,
Budgets, Learning, Skills, API Keys, plus link-tabs to `/billing` and `/organizations/`. Default
tab is Profile. `/profile` GET and `/settings/skills` redirect to their tab; the profile form
still POSTs to `/profile`, which validates colour/theme and redirects to
`/settings?saved=profile#profile`. `profile.html` and `settings/skills.html` are gone. When
adding a setting, add a tab panel (`data-tab-panel` + `validTabs`), not a new page. There is no
in-app password change (only Forgot password). Guard: `tests/test_settings_in_one_place.py`.

### Chat UI — Terminal Aesthetic
**Fonts:** Syne 800 (headings), IBM Plex Mono (code/mono), Outfit (body)
**Theme:** Dark terminal with animated grid background, orange accent `#ff6b35`

**Header layout (3 zones):**
- Left: sidebar toggle (☰)
- Center: primary nav (Chat / Dashboard / Workflows / Approvals) | secondary nav (Map / Learn); Settings is in the profile menu — orange underline on hover
- Right: Learning badge, credits, 🔔 bell, 📄 artifacts, 👤 profile menu (Light/Dark theme is a row in this menu)

**Export Chat** and **Clear Chat** moved to the profile (👤) dropdown menu.

**Reply formatting.** `formatMessage()` in `index.html` is a small markdown renderer: code
blocks, `#` headings, `|` tables (need the `|---|` row), `-`/`1.` lists, `---` rules, `code`
and **bold**. It escapes everything first (`escapeHtml` is a pure string function), so model
output can never inject HTML. Until 2026-10-16 it only handled code and bold, and every heading
and table showed as raw `##` and `|`. Tested in node by `tests/test_sandbox_step_by_step.py`.

**Phones in landscape (fixed 2026-10-14).** A sideways phone is wide but short, so
width-only media queries gave it the desktop layout and the message box fell off the
bottom of the screen. Both mobile blocks now read `@media (max-width: 768px), (max-height: 500px)`,
a `@media (max-height: 500px)` block shrinks the header and welcome banner, and
`body`/`.sidebar` use `100dvh` (phone `100vh` includes the area behind the browser bars).
Size new page chrome with `dvh`, and test any layout change at about 915x412 as well as
portrait. Pinned by `tests/test_chat_landscape_layout.py`.

**Phones held upright (fixed 2026-10-14).** The `max-width: 480px` block used to hide
`.header-nav` outright, and neither the ☰ sidebar nor the profile menu links to Dashboard,
Workflows, Approvals or Map, so they were unreachable from chat in portrait. The header now
wraps and the tabs become a second, sideways-scrolling row. Never hide the tab row without
putting those links somewhere else. Same test file.

---

### Seeded catalogs (import-time, not `scripts/`)

Any table a page needs non-empty to render must be seeded **at import in `app.py`**,
not by a script under `scripts/`. Gunicorn imports the module and never runs the
`__main__` block, and nothing in the deploy path runs `scripts/*.py`, so a
script-only seed leaves the table empty in production forever. This has now bitten
two separate catalogs (infrastructure templates, then pre-built workflows — see
CLAUDE_RUNBOOK.md's 2026-08-12 entry).

Pattern: put the data + an idempotent `seed_*()` (skip by name, return the count
added) in `services/starter_*.py`, call it from the import-time block in `app.py`
next to `seed_public_templates()` / `seed_workflow_templates()` inside a non-fatal
`try/except`, and leave `scripts/seed_*.py` as a thin CLI wrapper. The data cannot
live in `scripts/` — those modules do `from app import app, db`, so importing one
from `app.py` is circular. Current seeded catalogs: `services/starter_templates.py`
(`InfrastructureTemplate`), `services/starter_workflows.py` (`WorkflowTemplate`).

**The check-then-insert MUST run inside `services/seed_lock.py`'s `seed_lock(key)`.**
Production runs 3 sync gunicorn workers and all of them import `app.py` — and
therefore seed — at the same moment. "Read existing names, insert the rest" is not
idempotent across processes: each worker's read returns empty, so each inserts the
full catalog. This is not theoretical, it happened on the first deploy of the
workflow seed (8 templates became 16). `seed_lock` takes a Postgres
transaction-level advisory lock (`pg_advisory_xact_lock`, auto-released on
commit/rollback so a crashed worker can't strand it) and is a no-op on SQLite,
which is single-process. Give each catalog its own fixed, non-colliding lock key.

### Database Migration
**Auto-migration at startup:** Every time `app.py` starts, it runs `db.create_all()` (new tables) then inspects all SQLAlchemy models and runs `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for any columns in the model not yet in the DB. Output: `Auto-migration: added N column(s): table.column, ...`

**Manual options (if needed):**
```bash
python migrate_missing_columns.py        # CLI migration script
```
```javascript
// Browser console (must be logged in):
fetch('/api/run-migration', {method:'POST'}).then(r=>r.json()).then(console.log)
```

**Emergency: clear stuck streaming locks** (if `is_streaming` gets stuck):
```javascript
fetch('/api/reset-streaming', {method:'POST'}).then(r=>r.json()).then(console.log)
```

## Routine Docs Updates (Stop Hook)

Docs are kept in sync automatically via a `Stop` hook registered in
`.claude/settings.json` → `scripts/hooks/docs_update_check.py`.

**How it works:** every time the agent finishes a turn, the hook inspects the
git working tree. If source files changed (`.py`, `.html`, `.js`, `.css`,
`.yaml`, `.yml`) but no `.md` doc was updated, it returns a `block` decision
that instructs the agent to update `CLAUDE.md` / `CLAUDE_RUNBOOK.md` /
`CLAUDE_BILLING.md` before stopping. Once docs are touched, the next stop passes.

**Guards & opt-out:**
- Ignores changes under `tests/`, `scripts/hooks/`, `.claude/`, `logs/`.
- Honors `stop_hook_active` to avoid loops (won't re-block after one nudge).
- Fails open on any git/parse error (never blocks finishing work).
- Set `DOCS_HOOK_DISABLE=1` to bypass entirely.

For manual/on-demand doc refresh use the `/update-context` skill.

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
- `/integration-testing` - Pre-production gate: env preflight, full pytest, smoke tests, regression checks, security gate → ship/no-ship verdict

## Subagents (`.claude/agents/`)

- `executive-assistant` — owner-facing briefings, next-work ranking, PR/CI triage, TODOS.md/WORKLOG.md
  hygiene, and email/status drafts. Reads TODOS.md, CLAUDE.md "Not yet fixed" items, git log, GitHub,
  and Calendar/Gmail when connected. Proposes only: it never sends email, creates drafts, merges,
  pushes, or touches production itself — it returns proposed actions to the main session, which
  confirms with the owner and carries them out (a subagent cannot see the owner's conversation, so
  it cannot verify an approval).

## Code Style

- No emojis unless requested
- Minimal comments (self-documenting code)
- Type hints for function signatures
- SQLAlchemy for all database operations
