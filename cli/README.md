# DevOps Agent CLI

A terminal-first interface to DevOps Agent — run infrastructure commands directly, pipe output to scripts, and skip the browser entirely.

---

## Installation

```bash
npm install -g @devopsagent/cli
```

Requires Node.js 18+.

---

## Authentication

### 1. Get your API key

Log in to [devopsagent.io](https://devopsagent.io), go to **Settings → API Keys → Create Key**.

### 2. Log in

```bash
devopsagent login
```

You'll be prompted for your API key. It's stored at `~/.devopsagent/config.json`.

### 3. Verify

```bash
devopsagent whoami
```

---

## Commands

### AI Chat

Talk to the agent in natural language — same as the web UI:

```bash
# One-shot question
devopsagent ask "why is my pod in CrashLoopBackOff?"

# Pipe a question
echo "list ec2 instances in us-east-1" | devopsagent ask

# Interactive session
devopsagent chat
```

---

### AWS

```bash
# EC2
devopsagent aws ec2 list
devopsagent aws ec2 list --region eu-west-1
devopsagent aws ec2 list --output json | jq '.[] | select(.state=="running")'
devopsagent aws ec2 describe i-0abc123def456

# S3
devopsagent aws s3 list

# RDS
devopsagent aws rds list --region us-east-1

# EKS
devopsagent aws eks list --region us-west-2

# Lambda
devopsagent aws lambda list
```

**Flags:**
| Flag | Description |
|------|-------------|
| `-r, --region <region>` | AWS region (default: your configured region) |
| `-o, --output <format>` | `table` (default) or `json` |

---

### Kubernetes

```bash
# Pods
devopsagent k8s pods
devopsagent k8s pods --namespace production
devopsagent k8s pods --context my-cluster --output json

# Deployments
devopsagent k8s deployments -n kube-system

# Services
devopsagent k8s services --namespace staging

# Nodes
devopsagent k8s nodes

# Logs
devopsagent k8s logs my-pod-abc123
devopsagent k8s logs my-pod-abc123 --namespace production --lines 200
devopsagent k8s logs my-pod-abc123 --container sidecar
```

**Flags:**
| Flag | Description |
|------|-------------|
| `-n, --namespace <ns>` | Kubernetes namespace (default: `default`) |
| `-c, --context <ctx>` | Kubeconfig context |
| `-o, --output <format>` | `table` (default) or `json` |

---

### Terraform

```bash
devopsagent terraform plan --dir ./infra
devopsagent terraform apply --dir ./infra --auto-approve
devopsagent terraform output --dir ./infra
devopsagent terraform output --json
devopsagent terraform workspaces --dir ./infra
devopsagent terraform validate --dir ./infra

# Alias: tf
devopsagent tf plan --dir ./infra
```

**Flags:**
| Flag | Description |
|------|-------------|
| `-d, --dir <path>` | Working directory (default: `.`) |
| `--auto-approve` | Skip interactive approval (apply only) |
| `--var-file <file>` | Terraform var file |
| `--json` | JSON output (output command only) |

---

### Docker

```bash
# Containers
devopsagent docker ps
devopsagent docker ps --all

# Images
devopsagent docker images
devopsagent docker images --output json

# Logs
devopsagent docker logs my-container
devopsagent docker logs my-container --lines 500

# Stats
devopsagent docker stats
```

---

## Output Formats

All list commands support `--output table` (default) and `--output json`.

JSON output is designed for piping:

```bash
# Find all stopped EC2 instances
devopsagent aws ec2 list --output json | jq '.[] | select(.state=="stopped") | .instance_id'

# Count running pods per namespace
devopsagent k8s pods -n production --output json | jq 'length'

# Get a specific Terraform output value
devopsagent terraform output --json | jq '.database_url.value'
```

---

## Configuration

Config is stored at `~/.devopsagent/config.json`:

```json
{
  "api_key": "doa_live_...",
  "server_url": "https://devopsagent.io"
}
```

To point the CLI at a self-hosted instance:

```bash
devopsagent config set server_url http://localhost:5000
```

---

## Tier Requirements

| Command group | Required tier |
|---------------|--------------|
| `ask` / `chat` | Free and above |
| `aws`, `k8s`, `terraform`, `docker` | Professional ($99/mo) or Business ($299/mo) |

Direct tool commands (`aws`, `k8s`, etc.) call the DevOps Agent API and use your stored cloud credentials — no local AWS CLI or kubeconfig needed on the machine running the CLI.

---

## Troubleshooting

**"Not logged in"** — run `devopsagent login`

**"api_access_restricted"** — direct tool commands require Professional or Business tier. Use `devopsagent ask` for AI-mediated queries on lower tiers.

**"Invalid API key"** — regenerate your key at Settings → API Keys

**Wrong server** — check `~/.devopsagent/config.json` for `server_url`
