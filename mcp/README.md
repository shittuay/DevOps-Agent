# DevOps Agent MCP Server

Manage AWS, Azure, GCP, Kubernetes, Terraform, CI/CD, Docker, Ansible, and more from any MCP-compatible AI client. **401 tools across 13 modules** — all accessible via a single connection.

## Quickstart (Claude Desktop — recommended)

**Step 1:** Get your API key at [devopsagent.io/api-gateway/keys](https://devopsagent.io/api-gateway/keys)

**Step 2:** Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "devops-agent": {
      "command": "npx",
      "args": ["-y", "@devopsagent/mcp-server"],
      "env": { "DEVOPSAGENT_API_KEY": "doa_live_your_key_here" }
    }
  }
}
```

Restart Claude Desktop — all 401 tools appear automatically.

> **Requires Node.js 18+.** The `npx` command downloads and runs the bridge automatically on first use.

## Alternative: direct SSE (no Node.js required)

If you prefer not to use Node.js, connect directly via SSE:

```json
{
  "mcpServers": {
    "devops-agent": {
      "url": "https://devopsagent.io/mcp/sse",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}
```

## Connect via Claude.ai (OAuth)

1. Go to **Claude.ai → Settings → Connectors → Add custom connector**
2. Fill in:

| Field | Value |
|-------|-------|
| Name | `DevOps Agent` |
| Remote MCP server URL | `https://devopsagent.io/mcp` |
| OAuth Client ID | `claude-connector` |
| OAuth Client Secret | `devopsagent-mcp-secret-2026` |

3. Click **Add** — sign in with your DevOps Agent account to authorize.

## Tools

| Module | Count | What you can do |
|--------|-------|-----------------|
| AWS | 155 | EC2, S3, RDS, Lambda, ECS, EKS, IAM, VPC, CloudWatch, DynamoDB, and more |
| Kubernetes | 28 | Pods, Deployments, Services, Namespaces, Ingress, Jobs, Nodes |
| Azure | 36 | VMs, Storage, SQL, NSGs, Container Instances, VNets, Public IPs |
| GCP | 40 | Compute, GCS, Cloud SQL, GKE, Cloud Run, Pub/Sub, BigQuery, Functions |
| CI/CD | 21 | Jenkins (11) + GitHub Actions (10) |
| Docker | 22 | Containers, images, volumes, networks, compose, build, push |
| Terraform | 16 | init, plan, apply, destroy, state, workspaces, import |
| Ansible | 13 | Playbooks, ad-hoc, inventory, vault, galaxy |
| Monitoring | 12 | Prometheus, Datadog, Grafana |
| Alerting | 16 | PagerDuty + OpsGenie |
| SonarQube | 12 | Projects, quality gates, issues, analysis |
| Nexus | 12 | Repositories, components, assets |
| Git | 6 | Status, branches, commits, diff, PRs |

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DEVOPSAGENT_API_KEY` | Yes | — | API key from devopsagent.io/api-gateway/keys |
| `DEVOPSAGENT_MCP_URL` | No | `https://devopsagent.io/mcp/` | Override MCP endpoint (for self-hosted instances) |

## Server details

| Property | Value |
|----------|-------|
| MCP Protocol | `2025-03-26` |
| Transports | Streamable HTTP (`POST /mcp`) + HTTP+SSE (`GET /mcp/sse`) + stdio (via `npx`) |
| Auth | OAuth 2.0 (Claude.ai) or API Key (Claude Desktop / npx) |
| Registry | `io.github.shittuay/devops-agent` |
| Health check | `GET https://devopsagent.io/mcp/health` |

## Links

- **Website:** [devopsagent.io](https://devopsagent.io)
- **API Keys:** [devopsagent.io/api-gateway/keys](https://devopsagent.io/api-gateway/keys)
- **GitHub:** [github.com/shittuay/DevOps-Agent](https://github.com/shittuay/DevOps-Agent)
- **npm:** [@devopsagent/mcp-server](https://www.npmjs.com/package/@devopsagent/mcp-server)
