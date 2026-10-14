# DevOps Agent

An AI DevOps assistant you talk to in plain English. It works on your own AWS, Azure and GCP
accounts, Kubernetes clusters, CI/CD systems and on-call tools, with a safety check in front of
every risky action.

- **Live app:** [devopsagent.io](https://devopsagent.io)
- **Docs:** [devopsagent.io/docs](https://devopsagent.io/docs) (in the app) and the [`docs/`](docs/) folder
- **Developer API:** [devopsagent.io/developers](https://devopsagent.io/developers)

## What it does

- **Chat with your infrastructure.** Ask questions or give instructions ("list my EC2
  instances", "scale the api deployment to 4 replicas", "why did last night's deploy fail?").
  The agent picks from **749 tools across 18 modules** and runs them against your own accounts.
- **Workflows.** 46 pre-built, step-by-step jobs (launch a web server, audit IAM, troubleshoot
  pods, self-host an LLM, re-run a failed pipeline, page on-call, and more) across 14 categories.
  Each opens a short form, then runs in chat.
- **Safety.** Every tool call is risk-classified. Deletes, terminations, IAM changes and other
  risky operations need approval before they run (see [Approvals](docs/WEB_APPLICATION_GUIDE.md#approvals-and-change-requests)).
  Sandbox mode simulates everything without touching a real account.
- **Your data stays yours.** Cloud and integration credentials are stored per user, encrypted,
  and never shared with other users. The app never falls back to its own credentials.

| Area | Tools |
|------|------:|
| AWS (EC2, VPC, IAM, RDS, Lambda, ECS, EKS, S3, CloudFormation, Route 53, and more) | 352 |
| Kubernetes | 76 |
| Git | 47 |
| GCP | 42 |
| Azure | 38 |
| CI/CD (Jenkins, GitHub Actions, GitLab) | 36 |
| Terraform | 26 |
| Docker | 22 |
| GitHub | 19 |
| PagerDuty and OpsGenie | 16 |
| Ansible | 13 |
| Prometheus, Datadog and Grafana | 12 |
| SonarQube | 12 |
| Nexus | 12 |
| Security audit / pentest (off by default) | 12 |
| Cost, compliance and change governance | 10 |
| Shell commands on the agent host | 2 |
| Reachability probes (`http_check`, `tcp_check`) | 2 |
| **Total** | **749** |

## Using the app

1. Sign up at [devopsagent.io](https://devopsagent.io) and confirm your email.
2. Connect a cloud account in **Settings → Cloud Credentials**. For AWS, the recommended option
   is an IAM role (one-click CloudFormation quick-create); access keys also work.
3. Connect any third-party tools you use (GitHub, GitLab, Jenkins, PagerDuty, OpsGenie, Datadog,
   SonarQube, Nexus) in **Settings → Integrations**.
4. Chat, or open **Workflows** and pick one.

Want to try it without a cloud account? Turn on **Sandbox mode** (Settings → Learning). Tool
results are simulated and labelled `[Sandbox]`.

Plans: Free (20 credits a month), Starter ($29, 200 credits), Professional ($99, 1,000 credits)
and Business ($299, 3,000 credits). Free and Starter use Kimi K3; Professional and Business use
Claude. Extra credit packs are available on the Billing page.

### Other ways in

- **Claude.ai connector (MCP):** add `https://devopsagent.io/mcp` as a custom connector and sign
  in with your DevOps Agent account (and 2FA code, if you use 2FA). 704 tools are exposed this way.
- **Developer API:** `/api-gateway/v1/*`, authenticated with an `X-API-Key` header. See
  [/developers](https://devopsagent.io/developers).
- **Slack / Microsoft Teams:** see the ChatOps page in the app.

## Running it locally

Requirements: Python 3.11+, PostgreSQL (or let the tests use SQLite), and an Anthropic and/or
Moonshot (Kimi) API key.

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

export SECRET_KEY=change-me
export ANTHROPIC_API_KEY=sk-ant-...      # Claude tiers
export MOONSHOT_API_KEY=...              # Kimi tiers
export DATABASE_URL=postgresql://user:pass@localhost:5432/devops_agent   # required in production

python app.py                            # http://127.0.0.1:5000
```

New tables and columns are created automatically at startup. For a local Postgres and Redis, run
`docker compose up db redis` after setting `POSTGRES_PASSWORD` in `.env` (compose refuses to start
without it). The compose file's `app` service has no Dockerfile to build from, so run the app
itself with `python app.py`.

Cloud and integration credentials are **not** read from environment variables. Each user adds
their own in Settings once the app is running.

### Command-line mode

```bash
python main.py interactive     # chat in the terminal
python main.py ask "list pods in the default namespace"
python main.py tools           # list tools
```

The CLI has no signed-in user, so AWS, Azure and GCP tools refuse to run there (they only use
per-user credentials). Kubernetes (your local kubeconfig), local Git, Docker and Terraform work,
and integration tools work when you pass a token explicitly. See [docs/USER_GUIDE.md](docs/USER_GUIDE.md).

## Tests

```bash
pytest -q
```

Tests run against in-memory SQLite, so no database is needed. Two network-safety tests need
public DNS and fail in fully offline sandboxes.

## Project layout

```
app.py              Flask app: pages, chat endpoints, startup
models.py           SQLAlchemy models
src/agent/          Agent loop, safety classification, tool selection, guardrails
src/tools/          Tool modules (aws_tools.py, kubernetes_tools.py, ...)
services/           Business logic (credentials, workflows, approvals, billing, ...)
routes/             Blueprints for feature pages and APIs
api/v1/             Programmatic REST API (/api/v1)
templates/          Jinja2 pages
tests/              pytest suite
docs/               Guides and references
```

Contributors: read [CLAUDE.md](CLAUDE.md) first. It records the security rules and invariants
the code depends on (per-user isolation, SSRF guards, risk classification, guardrails), and
[CLAUDE_RUNBOOK.md](CLAUDE_RUNBOOK.md) records past incidents and fixes.

## Removed features

These were removed in October 2026 and are no longer part of the app: Optimize, Monitoring
(alert rules), Incidents (and playbooks) and Analysis (root-cause analysis). Incident work now
happens in chat, with the PagerDuty and OpsGenie tools and the Incident Response workflows.

## Support

- In the app: the chat, or `/docs`
- Email: support@devopsagent.io
- Security issues: security@devopsagent.io (see [/security](https://devopsagent.io/security))
