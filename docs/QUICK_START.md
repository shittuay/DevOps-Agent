# DevOps Agent Quick Start

From sign-up to your first real result in about five minutes.

---

## 1. Create an account

1. Go to [devopsagent.io](https://devopsagent.io) and click **Sign Up**.
2. Use a password with at least 8 characters, including an uppercase letter, a lowercase letter
   and a number.
3. Confirm your email from the link we send.

Two-factor authentication is optional but recommended: open **Profile**, find **Two-Factor
Authentication**, and choose an authenticator app or email codes. Once on, you'll be asked for a code at every sign-in, including
when you connect the Claude.ai connector.

## 2. Connect a cloud account

Open **Settings → Cloud Credentials**.

- **AWS (recommended: IAM role).** Click **Create role with CloudFormation**. It opens the AWS
  console with a ready-made, least-privilege role and a generated External ID. Create the stack,
  then paste the role ARN back into Settings. Access keys work too, as a fallback.
- **Azure:** subscription ID, tenant ID, client ID and client secret of a service principal.
- **GCP:** project ID and a service-account JSON key.

Credentials are encrypted and used only for your own requests.

No cloud account yet? Turn on **Sandbox mode** in **Settings → Learning**. Every result is then
simulated and labelled `[Sandbox]`, so you can try anything safely.

## 3. Connect your other tools (optional)

**Settings → Integrations** connects GitHub, GitLab, Jenkins, PagerDuty, OpsGenie, Datadog,
SonarQube and Nexus. The agent uses only the tools you connect here, never shared credentials.

## 4. Ask something

Open **Chat** and try:

```
What resources do I have in AWS?
List my EC2 instances in us-east-1
Show me pods in the production namespace
What did I spend on AWS last month, by service?
Which of my S3 buckets are public?
Show open high-urgency PagerDuty incidents
```

Risky actions (deletes, terminations, IAM and security-group changes, restarts and so on) are
not run straight away. On a personal account you confirm them yourself with **Confirm & run** in
the chat; in an organization, an owner or admin of the organization approves them. See
[Approvals](WEB_APPLICATION_GUIDE.md#approvals-and-change-requests).

## 5. Try a workflow

Open **Workflows**, pick one (for example *Launch a web server* or *Audit IAM users*), fill in the
short form, and it runs step by step in chat. There are 46 workflows across Compute, Security,
Monitoring, Storage, Database, Cost, Networking, AI/ML, App Hosting, Kubernetes, Incident
Response, IaC, CI/CD and On-Call.

---

## Where things are

| Page | Path | What it's for |
|------|------|---------------|
| Chat | `/chat` | Talk to the agent |
| Dashboard | `/dashboard` | Health score, costs and resources from your synced accounts |
| Workflows | `/workflows` | Pre-built step-by-step jobs |
| Templates | `/ai/templates` | Starter infrastructure templates |
| Map | `/infrastructure/map` | Visual map of your synced resources |
| Drift | `/drift/` | Compare live AWS state against a baseline |
| Analytics | `/analytics/` | Cost, resource and usage analytics |
| Security checks | `/dashboard` | Real checks on your connected AWS account (S3, security groups, RDS, IAM) |
| My requests | `/approvals/mine` | Confirm or cancel your own pending risky actions |
| Approvals | `/approvals` | Approve or reject your team's pending risky actions (organization owners and admins) |
| Changes | `/changes` | Change requests and the change audit trail |
| Learn | `/curriculum/` | Guided DevOps curriculum with an AI coach |
| Settings | `/settings` | Cloud credentials, integrations, notifications, budgets, learning, API keys |
| Billing | `/billing` | Plan, credits and credit packs |

## Plans

| Plan | Price | Credits / month | Model |
|------|-------|-----------------|-------|
| Free | $0 | 20 | Kimi K3 |
| Starter | $29 | 200 | Kimi K3 |
| Professional | $99 | 1,000 | Claude |
| Business | $299 | 3,000 | Claude |

Credit packs (100 to 1,000 credits) can be bought any time on the Billing page.

## Next steps

- [Web application guide](WEB_APPLICATION_GUIDE.md): every page in detail
- [Feature reference](FEATURE_REFERENCE.md): what the agent and the app can do
- [API reference](API_REFERENCE.md): the developer API and the programmatic API
- [Command-line guide](USER_GUIDE.md): running the agent from a terminal
