# DevOps Agent MCP Server

Manage AWS, Azure, GCP, Kubernetes, Terraform, CI/CD, Docker, Ansible, and more from any MCP-compatible AI client. **401+ tools across 13 modules** — all accessible via a single connection.

## What you can do

- **AWS** — EC2, S3, RDS, Lambda, ECS, EKS, IAM, VPC, CloudWatch, and 100+ more operations
- **Azure** — VMs, Storage, SQL, NSGs, Container Instances, VNets
- **GCP** — Compute, GCS, Cloud SQL, GKE, Cloud Run, Pub/Sub, BigQuery
- **Kubernetes** — Pods, Deployments, Services, Namespaces, Ingress, Jobs, RBAC
- **Terraform** — init, plan, apply, destroy, state, workspaces, import
- **CI/CD** — Jenkins (11 tools) + GitHub Actions (10 tools)
- **Docker** — containers, images, volumes, networks, compose, build, push
- **Ansible** — playbooks, ad-hoc, inventory, vault, galaxy
- **Monitoring** — Prometheus, Datadog, Grafana
- **Alerting** — PagerDuty + OpsGenie
- **SonarQube** — projects, quality gates, issues, analysis
- **Nexus** — repositories, components, assets

## Connect via Claude.ai

1. Go to **Claude.ai → Settings → Connectors → Add custom connector**
2. Fill in:

| Field | Value |
|-------|-------|
| Name | `DevOps Agent` |
| Remote MCP server URL | `https://devopsagent.io/mcp` |
| OAuth Client ID | `claude-connector` |
| OAuth Client Secret | `devopsagent-mcp-secret-2026` |

3. Click **Add** — sign in with your DevOps Agent account to authorize.

## Connect via Claude Desktop

Generate an API key at [devopsagent.io/api-gateway/keys](https://devopsagent.io/api-gateway/keys), then add to your `claude_desktop_config.json`:

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

Restart Claude Desktop — all tools appear automatically.

## Server details

| Property | Value |
|----------|-------|
| MCP Protocol | `2025-03-26` |
| Transport | Streamable HTTP (`POST /mcp`) + HTTP+SSE (`GET /mcp/sse`) |
| Auth | OAuth 2.0 (Claude.ai) or API Key (Claude Desktop) |
| Registry | `io.github.shittuay/devops-agent` |
| Health check | `GET https://devopsagent.io/mcp/health` |

## Links

- **Website:** [devopsagent.io](https://devopsagent.io)
- **Documentation:** [devopsagent.io/docs#mcp-server](https://devopsagent.io/docs#mcp-server)
- **API Keys:** [devopsagent.io/api-gateway/keys](https://devopsagent.io/api-gateway/keys)
- **GitHub:** [github.com/shittuay/DevOps-Agent](https://github.com/shittuay/DevOps-Agent)
