# Documentation

## For users

| Guide | What it covers |
|-------|----------------|
| [Quick start](QUICK_START.md) | Sign-up to first result in five minutes |
| [Web application guide](WEB_APPLICATION_GUIDE.md) | Every page in the app, including approvals |
| [Feature reference](FEATURE_REFERENCE.md) | What the agent and the app can do, tool counts |
| [API reference](API_REFERENCE.md) | Developer API, programmatic API, Claude.ai connector, webhooks |
| [Automation cookbook](AUTOMATION_COOKBOOK.md) | Example chat requests by scenario |
| [IAM policies](iam-policies.md) | The published least-privilege AWS policies |
| [Pentest guide](PENTEST_GUIDE.md) | The optional security-testing tools (off by default) |
| [Command-line guide](USER_GUIDE.md) | Running the agent from a terminal |

## For operators and contributors

| Document | What it covers |
|----------|----------------|
| [../CLAUDE.md](../CLAUDE.md) | Architecture, security invariants and conventions; read first |
| [../CLAUDE_RUNBOOK.md](../CLAUDE_RUNBOOK.md) | Past incidents and fixes |
| [execution-integrity.md](execution-integrity.md) | Read-back verification, audit trail and IaC fallback |
| [governance-refactor.md](governance-refactor.md) | Declared tool capabilities |
| [aws-account-migration.md](aws-account-migration.md) | Moving the platform AWS account |
| [DATABASE_BACKUP.md](DATABASE_BACKUP.md) | Production database backups |
| [sonarqube.md](sonarqube.md) | Static analysis setup and findings not to auto-fix |

## Historical

`archive/`, `superpowers/` (design specs and plans), `designs/` and `blog/` record how things
were at the time they were written. They mention features that have since changed or been removed
(Optimize, Monitoring, Incidents, Analysis) and are not kept up to date.
