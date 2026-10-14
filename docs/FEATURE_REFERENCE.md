# DevOps Agent Feature Reference

What the app and the agent can do today. For how to use each page, see the
[web application guide](WEB_APPLICATION_GUIDE.md).

Everything works against **your own** connected accounts. If you haven't connected one, features
say so and do nothing, unless you turn on Sandbox mode, where results are simulated and labelled
`[Sandbox]`.

---

## The agent

### Chat (`/chat`)

- Ask in plain English; the agent picks tools and runs them against your accounts.
- 749 tools across 18 modules (table below). Each turn the agent is offered only the tools
  relevant to the request, and can search the full catalog when it needs something else.
- Conversations are saved per user; tool calls made during a reply are shown with it.
- Artifacts panel: save generated runbooks, reports and specs as versioned documents and
  download them as Markdown.
- Context links: pages such as the infrastructure map can open chat already focused on a resource.
- Skills (`/settings/skills`): built-in expertise (AWS cost optimisation, Kubernetes
  troubleshooting, security hardening, incident runbooks, Terraform) added to the agent when your
  message matches, plus a summary of your synced infrastructure.

### Safety

| Check | What it does |
|-------|--------------|
| Risk classification | Every tool call is low, medium or high risk. Deletes and terminations are high; restarts, stops, IAM, firewall and other changes are medium; reads and most creates are low. Production targets raise high to critical. |
| Approvals | Medium- and high-risk calls from chat, the Claude.ai connector and both APIs wait for approval. Approvers and Admins run their own medium-risk calls directly and confirm their own high-risk ones. Your organization's owners and admins approve them; if nobody else could (a solo account, or you're the only owner), you confirm them yourself in the chat card or on `/approvals/mine`. If the request can't be recorded, the action is blocked. See [Approvals](WEB_APPLICATION_GUIDE.md#approvals-and-change-requests). |
| Change requests | `/changes`: a request, approval and execution record with rollback data. |
| Guardrails | Prompt-injection and abuse screening on every chat entry point, with a temporary block after repeated violations. |
| Secret redaction | Keys, tokens and connection strings are redacted from replies before they are shown or saved. |
| Read-back verification | After a create, update or delete, the agent re-reads the resource and reports whether the change is confirmed yet. |
| Sandbox mode | Simulates every tool result. Settings → Learning. |

### Models and plans

| Plan | Price | Credits / month | Model |
|------|-------|-----------------|-------|
| Free | $0 | 20 | Kimi K3 |
| Starter | $29 | 200 | Kimi K3 |
| Professional | $99 | 1,000 | Claude |
| Business | $299 | 3,000 | Claude |

Credit packs of 100, 250, 500 and 1,000 credits are on the Billing page.

---

## Workflows (`/workflows`)

46 pre-built jobs in 14 categories: Compute, Security, Monitoring, Storage, Database, Cost,
Networking, AI/ML, App Hosting, Kubernetes, Incident Response, IaC, CI/CD and On-Call.

- Each opens a short form (region, CIDR, names and so on), then runs step by step in chat.
- Network-facing workflows default to your own IP, never the whole internet, unless the workflow
  is a public web app.
- Passwords left blank are generated; none are hard-coded.
- Read-only workflows (Incident Response, IAM audit, compliance check and others) never change
  anything. Audit workflows that offer fixes change nothing until you name the items.
- Provisioning workflows end with a teardown step.
- CI/CD and On-Call workflows need the matching integration (Settings → Integrations) and ask
  before their one write (re-run, retry, page).

---

## Infrastructure pages

| Page | Path | What it does |
|------|------|--------------|
| Dashboard | `/dashboard` | Health score, costs and resources from your synced cloud accounts |
| Templates | `/templates` | Starter infrastructure templates |
| Infrastructure map | `/infrastructure/map` | Pan-and-zoom map of synced resources; open any resource in chat |
| Drift detection | `/drift/` | Capture a baseline from your live AWS account (EC2, security groups, S3, RDS) or import one from a `terraform.tfstate`, then scan for property-level changes and removed resources |
| AI infrastructure | `/ai/` | Browse, preview and clone templates; past deployments. Its plain-English request box currently errors, so use Chat |
| Predictive scaling | `/scaling/` | Scaling recommendations from metric history. Nothing feeds it metrics yet, so it is normally empty |

## Analytics (`/analytics/`)

Cost, performance and resource views built from your AWS Cost Explorer and CloudWatch data and
the app's own records. Shows zeros or empty charts when there is no data; it never invents
numbers. Export as JSON or CSV.

## Compliance (`/compliance/`)

Frameworks (SOC 2, HIPAA, PCI DSS, GDPR, ISO 27001, NIST, CIS), policies you can enable and
edit, evidence uploads, and exportable reports.

---

## Integrations

### Cloud accounts (Settings → Cloud Credentials)

- **AWS:** IAM role (recommended, one-click CloudFormation quick-create with an External ID) or
  access keys. Published least-privilege read-only and management policies.
- **Azure:** service principal.
- **GCP:** service-account JSON key.

Credentials are encrypted per user and never fall back to the platform's own.

### Third-party tools (Settings → Integrations)

GitHub, GitLab, Jenkins, PagerDuty, OpsGenie, Datadog, SonarQube and Nexus. Saved secrets are
write-only and are only ever sent to the server URL you saved.

### Notifications (`/notifications/`, Settings → Notifications)

- Slack and Microsoft Teams channels, with a test button.
- Toggles for change, security, cost and alert notifications; budget alerts in Settings → Budgets.

### ChatOps (`/chatops/`)

Slack and Teams bot. Link your chat identity with a one-time code from the ChatOps page, then use
`/devops help`, `/devops link <code>`, `/devops oncall` and, for admins, `/devops deployments`.

### Inbound Git webhooks (`/webhooks/`)

Receivers for GitHub (HMAC signature), GitLab (secret token) and Bitbucket. The events dashboard
is admin-only.

### Developer API, programmatic API and connector

| Interface | Base path | Auth |
|-----------|-----------|------|
| Developer API | `/api-gateway/v1` | `X-API-Key` header |
| Programmatic API | `/api/v1` | `X-API-Key` header or Bearer |
| Claude.ai connector (MCP) | `/mcp` | OAuth sign-in (with 2FA), or an API key |

API keys are created at `/api-gateway/keys` with scopes `read`, `write`, `delete` and `admin`.
Details: [API reference](API_REFERENCE.md).

---

## Accounts, teams and administration

| Area | Details |
|------|---------|
| Sign-in | Email or username; passwords need 8+ characters with upper case, lower case and a number; 5 wrong attempts lock the account for 15 minutes |
| 2FA | Authenticator app or email code, set up from Profile |
| SSO | Organisation-level SSO (`/auth/sso/*`) |
| Sessions | 24 hours; "remember me" 30 days |
| Organisations (`/organizations/`) | Members, invitations, teams; organisation roles Owner, Admin, Member |
| Platform roles | Admin, Approver, User (default), Viewer. Only platform admins can change them |
| Admin (`/admin/`) | User search, role changes, lock/unlock, delete, audit log, system settings |
| Learning (`/curriculum/`) | Guided curriculum with an AI coach and quizzes; Learning mode in Settings |

---

## Tool count by module

| Module | Tools |
|--------|------:|
| AWS | 352 |
| Kubernetes | 76 |
| Git | 47 |
| GCP | 42 |
| Azure | 38 |
| CI/CD (Jenkins, GitHub Actions, GitLab) | 36 |
| Terraform | 26 |
| Docker | 22 |
| GitHub | 19 |
| Alerting (PagerDuty, OpsGenie) | 16 |
| Ansible | 13 |
| Monitoring (Prometheus, Datadog, Grafana) | 12 |
| SonarQube | 12 |
| Nexus | 12 |
| Pentest (off by default) | 12 |
| DevOps operations (cost, compliance, change governance) | 10 |
| Command | 2 |
| Verification (`http_check`, `tcp_check`) | 2 |
| **Total** | **749** |

Docker, Terraform and command tools run on the DevOps Agent server, not on your machine.

---

## Removed features

Removed in October 2026: Optimize (`/optimization`), Monitoring alert rules (`/monitoring`),
Incidents and playbooks (`/incidents`) and root-cause Analysis (`/analysis`). Incident work now
happens in chat, using the PagerDuty and OpsGenie tools and the Incident Response workflows.
