# DevOps Agent Command-Line Guide

Most people use DevOps Agent in the browser at [devopsagent.io](https://devopsagent.io); see the
[quick start](QUICK_START.md) and the [web application guide](WEB_APPLICATION_GUIDE.md). This
page covers the command-line interface (`main.py`), which runs the agent from a local checkout.

## What works in the CLI

The CLI has no signed-in user. That matters, because the app only ever uses **per-user**
credentials:

| Works | Doesn't work |
|-------|--------------|
| Kubernetes, using your local kubeconfig | AWS, Azure and GCP tools (they refuse to run without a signed-in user's saved credentials) |
| Local Git repositories | Integration tools (GitHub Actions, GitLab, Jenkins, PagerDuty, OpsGenie, Datadog) **unless** you pass the token in your request |
| Terraform and Ansible on this machine | Workflows, approvals, dashboards and everything else in the web app |
| Shell commands on this machine | |

The CLI registers the command, cloud, Kubernetes, Git, CI/CD, Terraform, monitoring, Ansible,
alerting and (if enabled) pentest modules. Docker, SonarQube, Nexus and GitHub repository tools
are web-app only.

For cloud accounts, use the web app (or the [developer API](API_REFERENCE.md)), which runs as
you with your saved credentials.

## Install

```bash
git clone <repo-url> devops-agent && cd devops-agent
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py --version
```

Python 3.11 or newer is recommended.

## Configure

```bash
python main.py init
```

This copies `config/config.yaml.example` to `config/config.yaml` and creates `config/.env`. Put
your model key in `config/.env`:

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

Both commands below accept `--config/-c` (path to a config YAML) and `--env/-e` (path to a
`.env` file).

## Use

```bash
python main.py interactive                              # chat in the terminal
python main.py ask "list pods in the default namespace" # one question, then exit
python main.py tools                                    # list the registered tools
```

Example requests that work locally:

```
Show pods in the production namespace
Get logs from the api-server pod, last 100 lines
Scale the frontend deployment to 4 replicas
Show the last 10 commits in /path/to/repo
Run terraform plan in /path/to/infra
Query Prometheus at http://prometheus.internal:9090 for up
```

Tool calls still go through the safety classifier, but the CLI has no approval queue behind it.
Point it at test clusters and repositories first, and use read-only kubeconfig contexts for
exploring.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Agent not initialized" | `ANTHROPIC_API_KEY` is missing from `config/.env`; run `python main.py init` and add it |
| "Authentication required" from an AWS, Azure or GCP tool | Expected in the CLI; use the web app for cloud accounts |
| "connect it in Settings > Integrations" | Pass the token in your request (for example "using token ghp_...") or use the web app |
| Kubernetes config not found | Check `~/.kube/config` or set `KUBECONFIG`; confirm `kubectl get pods` works |
| Command timed out | Raise `safety.command_timeout_seconds` in `config/config.yaml` |

Logs are written to `logs/agent.log`.
