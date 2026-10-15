# DevOps Agent Web Application Guide

A page-by-page guide to the DevOps Agent web app at [devopsagent.io](https://devopsagent.io).
For a five-minute start, see [QUICK_START.md](QUICK_START.md).

---

## Contents

1. [Accounts and sign-in](#accounts-and-sign-in)
2. [Chat](#chat)
3. [Workflows](#workflows)
4. [Dashboard](#dashboard)
5. [Settings](#settings)
6. [Approvals and change requests](#approvals-and-change-requests)
7. [Infrastructure pages](#infrastructure-pages)
8. [Analytics](#analytics)
9. [Security checks](#security-checks)
10. [Notifications](#notifications)
11. [Developer API and the Claude.ai connector](#developer-api-and-the-claudeai-connector)
12. [Organizations and teams](#organizations-and-teams)
13. [Learning](#learning)
14. [Billing](#billing)
15. [Administration](#administration)
16. [Public pages](#public-pages)
17. [Troubleshooting](#troubleshooting)

---

## Accounts and sign-in

**Sign up** with an email, username and password. Passwords need at least 8 characters with an
uppercase letter, a lowercase letter and a number. Confirm your email from the link we send.

**Sign in** with your email (any capitalisation) or exact username.

- After 5 wrong passwords the account locks for 15 minutes.
- Sessions last 24 hours; "Remember me" keeps you signed in for 30 days.
- **Forgot password** emails a reset link.

**Two-factor authentication** (Profile → Two-Factor Authentication): choose an authenticator app
or emailed codes. Backup codes are issued when you turn it on. 2FA belongs to the account, so it
works on every device. A code screen stays valid for 10 minutes; after 5 wrong codes, 2FA locks for
15 minutes. Lost your authenticator? Use **Reset 2FA** on the code screen to get an email link.

**Single sign-on:** if your organization enforces SSO for your email domain, use **Sign in with
SSO**. Password sign-in is then refused for that account.

---

## Chat

The chat (`/chat`) is the main way to work. Type a request in plain English; the agent picks the
right tools, runs them against your connected accounts, and reports what happened.

**Examples**

```
List my EC2 instances in us-east-1 and their states
Which security groups allow 0.0.0.0/0 on port 22?
What did I spend on AWS last month, by service?
Show pods in the production namespace that are not Running
Why did the last run of the deploy workflow in owner/repo fail?
Who is on call in OpsGenie right now?
```

**What you'll see**

- Tool activity streams in as the agent works, then the final answer.
- Risky actions don't run straight away. Depending on your role they wait for an approver; see
  [Approvals](#approvals-and-change-requests).
- After a create, delete or update, the agent reads the resource back to confirm the change.
  "Unconfirmed" means the cloud API hadn't caught up yet, not that it failed.
- Secrets (API keys, private keys, connection strings) are redacted from replies.

**Header and menus**

- **Sidebar:** past conversations. Click to reopen; hover to delete.
- **Model:** the toolbar toggle switches between your plan's default model and the alternatives
  your plan allows.
- **Artifacts (📄):** documents the agent generated (runbooks, reports), versioned, with Markdown
  export.
- **Profile menu (👤):** Export Chat, Clear Chat, tools list, session stats, Billing and Teams
  (your organizations).

Each reply costs credits; the balance is shown in the header, with a warning when it gets low.

---

## Workflows

**Workflows** (`/workflows`) are 46 pre-built, step-by-step jobs in 14 categories: Compute,
Security, Monitoring, Storage, Database, Cost, Networking, AI/ML, App Hosting, Kubernetes,
Incident Response, IaC, CI/CD and On-Call.

1. Pick a workflow and click **Run**.
2. Fill in the short form (region, instance size, allowed IP range, and so on). Your current IP
   is pre-filled where a firewall rule needs one; leave password fields blank to have one
   generated.
3. The workflow opens in chat and runs step by step.

Safety rules built into the workflows:

- Anything opened to the internet asks for a specific IP range; `0.0.0.0/0` is refused except for
  the two public web-app workflows.
- Audit workflows (IAM, public S3 buckets, idle resources) change nothing until you name what to
  fix.
- CI/CD and On-Call workflows use the tools you connected in **Settings → Integrations**, and ask
  "yes" before their one write (re-run, retry, page).
- Provisioning workflows end with teardown steps so you can clean up.

Past runs and their status are listed on the page.

---

## Dashboard

The dashboard (`/dashboard`) summarises your connected accounts:

- **Health score** (A–F) from open security findings, cost waste and active critical alerts.
- **Spend**: the last 30 days from AWS billing when Cost Explorer is on, with AWS's own forecast.
  Otherwise an **estimated monthly cost** from list prices, labelled as such, and no forecast.
- **Estimated savings**: recommendations backed by evidence from your account (CloudWatch CPU,
  how long an instance has been stopped, unattached volumes). Savings figures are estimates.
  **Fix in chat** opens chat with the recommendation filled in; the agent checks the resource and
  asks before changing anything. **Dismiss** hides it for good.
- **Security checks**: see [Security checks](#security-checks).
- **Total resources** and the last **infrastructure sync** (use **Sync now** to refresh).

With no cloud account connected, it shows zeros rather than sample data.

---

## Settings

`/settings` has six tabs.

| Tab | What it does |
|-----|--------------|
| **Cloud Credentials** | Connect AWS, Azure and GCP. AWS: IAM role (recommended; one-click CloudFormation quick-create with a generated External ID) or access keys. Azure: subscription ID, tenant ID, client ID and secret of a service principal, default location. GCP: project ID, service-account JSON key, default region. Each offers read-only or management policy levels. |
| **Notifications** | Slack or Teams channels for new cost savings, security findings, change requests and budget alerts. |
| **Budgets** | Monthly, weekly or daily spend thresholds, checked once a day against AWS billing (Cost Explorer must be on). Going over sends an email, a Slack/Teams message and a `cost.threshold` webhook, once per period. |
| **Learning** | Learning mode (the agent explains concepts), level (beginner, intermediate, advanced), Sandbox mode, and practice scenarios. |
| **Integrations** | GitHub, GitLab, Jenkins, PagerDuty, OpsGenie, Datadog, SonarQube and Nexus. Secrets are write-only: never shown again after saving. A saved secret is only ever sent to the server URL you saved with it. |
| **API Keys** | Keys for the developer API and the programmatic API. |

**Skills** (`/settings/skills`) turns built-in expertise packs on or off (AWS cost optimization,
Kubernetes troubleshooting, security hardening, incident runbooks, Terraform best practices) and
shows the summary the agent keeps of your synced infrastructure.

**Sandbox mode** simulates every tool result (labelled `[Sandbox]`), so nothing touches a real
account. It's for learning and demos, and is not a substitute for a connected account.

---

## Approvals and change requests

Every tool call is classified by risk before it runs:

| Risk | Examples | What happens |
|------|----------|--------------|
| Low | Reads, lists, most creates | Runs immediately |
| Medium | Stop, restart, update, scale, IAM and firewall-rule changes, triggering pipelines, paging on-call | Needs approval |
| High | Delete, terminate, destroy, and anything that reveals a secret | Needs approval; escalates to critical for production resources |

**How approval works today**

- **If your role is User** (the default for every new account): a medium- or high-risk action
  from chat or the Claude.ai connector doesn't run straight away. It becomes a request that
  expires after 24 hours if nobody acts on it. When it runs, it uses your credentials and the
  result is posted back into your conversation.
- **If you're in an organization,** the organization's **owners and admins** approve it, along
  with anyone in the organization who has the platform **Approver** role. They're notified in
  the app and by email and approve on the Approvals page. You can't approve your own request,
  but you can cancel it on **My requests**.
- **If nobody else could approve it** (you aren't in an organization, or you're the only owner
  or admin of yours), you confirm it yourself: the chat card shows **Confirm & run** and
  **Cancel**, and the same requests are listed on **My requests** (`/approvals/mine`), which is
  also where you confirm actions asked for through the Claude.ai connector.
- **If the request can't be recorded** (a database error, say), the action is blocked rather
  than run.
- **If your role is Approver or Admin:** your own medium-risk actions run directly. Your own
  high-risk actions (delete, terminate, destroy, anything that reveals a secret) still wait for
  you to click **Confirm & run**: one message shouldn't be enough to delete production. Nobody
  else approves those for you.
- **Through the API:** the developer API (and the deprecated `/api/v1`) apply the same rules; see the
  [API reference](API_REFERENCE.md#risky-tools-and-approvals).
- **Sandbox mode:** never creates approval requests; everything is simulated.
- **Missing AWS permissions:** when AWS refuses an action because DevOps Agent's role lacks a
  permission, the chat shows an **AWS permission needed** card with the exact policy. It is
  approved like any high-risk request. On yes, either you add the policy in AWS (the card shows
  the console path and a CLI command) and click **I added it, retry**, or, if you turned on
  self-grant in Settings → AWS Configuration (needs the CloudFormation stack with
  `AllowSelfGrant=Yes`), the agent adds it to its own role and retries. If AWS then needs
  another permission for the same task, a new card appears. See
  [IAM policies](iam-policies.md#letting-the-agent-add-missing-permissions-allowselfgrant).

**My requests** (`/approvals/mine`, everyone): your own pending agent requests and change
requests, with Confirm (when nobody else could approve) and Cancel.

**Approvals page** (`/approvals`, organization owners and admins, plus platform Approvers and
Admins): one queue for your team's pending agent requests and change requests, with approve and
reject (with a note). **History** (`/approvals/history`) lists decided requests.

**Change requests** (`/changes`) are the planned, team-reviewed route: ask the agent to "create a
change request" (or create one on the page). It is decided in Approvals by the same rules as agent
requests (an owner or admin of your organization; you, if nobody else could), then executed from
`/changes`, with rollback data saved first. Actions run directly from chat are also recorded
there as executed changes, so the page doubles as an audit trail.

Organization owners and admins make someone an organization admin from the organization's Members page.
The platform Approver and Admin roles are set by platform admins (Admin → Users).

---

## Infrastructure pages

**Templates** (`/ai/templates`): curated starter infrastructure templates you can preview and copy.

**Map** (`/infrastructure/map`): a pan-and-zoom map of your synced resources. Hover a resource and
choose **Investigate** to open chat about it. Plain scroll pans; Ctrl/⌘ + scroll zooms.

**Drift detection** (`/drift/`): compare live AWS state with a baseline.

- Create baselines by **capturing your account's current state** (EC2, security groups, S3, RDS)
  or **importing a `terraform.tfstate`**.
- **Scan** to see changed or removed properties. A baseline only pins the properties it lists;
  extra live properties aren't treated as drift.
- If the account can't be read, the scan reports an error rather than an empty or clean result.

**AI Infrastructure** (`/ai/`): describe AWS servers, databases, storage buckets or VPCs in plain
English ("create 3 small servers and a database named shop in us west") and get Terraform to
review and apply yourself. Nothing is created in your account from this page, and no prices are
shown; ask in **Chat** to build it or for live pricing, and for Azure or Google Cloud. The
generated code looks up the newest Ubuntu 22.04 image from Canonical rather than hardcoding one,
keeps databases private and encrypted with an AWS-managed password, and blocks public access on
buckets. Load balancers aren't generated here, because they need your subnets. The page also
lets you browse, preview and clone templates, and view past deployments. The
**Recommendations** tab is empty until a live data source feeds it.

---

## Analytics

`/analytics/` (with **Costs**, **Performance** and **Resources** views) shows spend by service
and over time, a cost forecast, resource counts and utilization, and deployment activity.
Everything comes from your connected AWS account (Cost Explorer, CloudWatch) or the app's own
records of your resources and tool runs; without data it shows zeros, never invented numbers.

---

## Security checks

The Dashboard's **Security checks** section reads your connected AWS account and lists what it
finds: public S3 buckets or buckets without encryption, security groups open to the internet on
sensitive ports, public or unencrypted RDS databases, and IAM console users without MFA or with
old access keys. **Run checks** re-reads the account; findings that are fixed drop off on the next
run, and **Dismiss** hides one you have accepted. If an area could not be read (for example, a
missing permission), it says so instead of reporting it as clean.

This is not a compliance assessment. There are no SOC 2, HIPAA or PCI scores. You can also ask
the agent to "scan my account for security issues".

---

## Notifications

**Settings → Notifications**: connect Slack and Teams channels, test them, and choose which
events reach them (change requests, security findings, cost savings, budget alerts).

**Weekly digest:** on Sundays, accounts with a connected cloud get one email with their health
grade, savings found that week and open critical findings. The email has a one-click unsubscribe
link (it also stops onboarding emails; budget alerts are unaffected).

---

## Developer API and the Claude.ai connector

**Developer API** (`/api-gateway/`, Professional and Business): API keys, outgoing webhooks,
usage, and docs. Calls go to `/api-gateway/v1/*` with an `X-API-Key` header. Each key has a
daily request limit (1,000 by default). Risky tools follow the same approval rules as chat: the
first call returns an `approval_id`, which you send back to confirm (or which waits for your
organization's approval). Full reference: [/developers](https://devopsagent.io/developers) and
[API_REFERENCE.md](API_REFERENCE.md).

**Claude.ai connector:** add `https://devopsagent.io/mcp` as a custom connector in Claude.ai and
sign in with your DevOps Agent account (and 2FA code). Risky actions follow the same approval
rules as chat.

---

## Organizations and teams

**Organizations** (`/organizations/`): create one, invite members by email, and give them an
organization role (owner, admin, member). Organizations also have teams and, for admins, an
**SSO** page (OIDC or SAML, with verified email domains and optional enforcement).

Organization membership decides which approvers can see your approval requests and change
requests.

---

## Learning

**Learn** (`/curriculum/`): a phased DevOps curriculum with an AI coach and quizzes. Combine with
**Learning mode** and **Sandbox mode** in Settings to practise safely.

---

## Billing

`/billing` shows your plan, credits used this month, and history.

| Plan | Price | Credits / month | Model |
|------|-------|-----------------|-------|
| Free | $0 | 20 | Kimi K3 |
| Starter | $29 | 200 | Kimi K3 |
| Professional | $99 | 1,000 | Claude |
| Business | $299 | 3,000 | Claude |

Credit packs (100, 250, 500 or 1,000 credits) can be bought at any time. Payments use Stripe
(prices in Naira are also offered).

---

## Administration

Admins (`/admin/`) see user counts and recent sign-ups, manage users (search, change role, lock,
unlock, delete), browse the usage audit log, and change system settings.

Platform roles:

| Role | Can |
|------|-----|
| Admin | Everything, including user management |
| Approver | Approve or reject risky actions and change requests in their organizations |
| User | Normal use; risky actions need approval |
| Viewer | Read-only |

---

## Public pages

- `/status`: health of the app and the providers it depends on (database, Kimi/Claude, Stripe,
  email), probed every couple of minutes. `/api/status/health` returns the same as JSON (200 when
  all operational, 503 otherwise) for uptime monitors.
- `/security`: how credentials are handled, the published IAM policies, and how to report a
  vulnerability.
- `/docs`, `/developers`, `/about`, `/privacy-policy`, `/usage-policy`.

---

## Troubleshooting

| Problem | What to do |
|---------|-----------|
| Account locked | Wait 15 minutes, or reset your password |
| 2FA code rejected | Check the device clock (authenticator) or use the newest email; paste with or without the space; use a backup code; or **Reset 2FA** |
| "Connect a cloud account" | Add credentials in Settings → Cloud Credentials |
| "Connect it in Settings → Integrations" | Add that tool in Settings → Integrations |
| Action stuck at "Waiting for an approver" | An Approver or Admin in your organization must approve it on `/approvals`; requests expire after 24 hours |
| Out of credits | Buy a credit pack or upgrade on `/billing` |
| Claude.ai connector says the credentials were rejected | See CLAUDE_RUNBOOK.md (Cloudflare "AI Crawlers" rule) |

---

## Removed features

Optimize, Monitoring (alert rules), Incidents (and playbooks), Analysis (root-cause analysis) and
Predictive Scaling were removed in October 2026. Incident work now happens in chat with the PagerDuty and OpsGenie
tools and the Incident Response workflows.
