# DevOps Agent MCP Server

Manage AWS, Azure, GCP, Kubernetes, Terraform, CI/CD, Docker, Ansible, and more from any MCP-compatible AI client. **704 tools across 13 modules** — all accessible via a single connection.

## Prerequisites

- **Node.js 18+** — required to run the stdio bridge via `npx`
- An API key from [devopsagent.io](https://devopsagent.io) (see [Getting Your API Key](#getting-your-api-key))
- No npm account needed — you're just a user of the published package

## Getting Your API Key

1. Log in at [devopsagent.io](https://devopsagent.io)
2. Navigate to **Settings → API Keys**
3. Click **Generate Key** — your key will be prefixed with `doa_live_`
4. Copy it and use it as `DEVOPSAGENT_API_KEY` in the steps below

## Installation via npm (Claude Desktop / Claude Code)

**Step 1:** Get your API key (see above)

**Step 2:** Find your Claude Desktop config file:
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

**Step 3:** Add this to the file (create it if it doesn't exist):

```json
{
  "mcpServers": {
    "devops-agent": {
      "command": "npx",
      "args": ["-y", "@devopsagent/mcp-server"],
      "env": {
        "DEVOPSAGENT_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

**Step 4:** Fully quit and restart Claude Desktop.

All 704 tools will appear automatically under the tools (hammer) icon in the chat input.

> The `npx` command downloads and runs the bridge automatically on first use — nothing else to install.

## Installation via Remote URL (Claude.ai Connectors)

No Node.js needed for this method — Claude.ai connects directly to the hosted server.

1. Go to **Claude.ai → Settings → Connectors → Add Integration**
2. Enter the Integration URL: `https://devopsagent.io/mcp/`
3. Claude.ai will trigger OAuth automatically — log in with your devopsagent.io account to authorize
4. All 704 tools become available immediately

## Verifying the Connection

Run this curl command to confirm your API key works before adding it to Claude Desktop:

```bash
curl -s https://devopsagent.io/mcp/ \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

Expected response:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2025-03-26",
    "serverInfo": { "name": "DevOps Agent", "version": "1.0.7" },
    "capabilities": { "tools": { "listChanged": false } }
  }
}
```

If you get a `401` response, your API key is invalid or not yet created.

You can also test the stdio bridge directly in your terminal:

```bash
DEVOPSAGENT_API_KEY=your_api_key_here npx -y @devopsagent/mcp-server@latest
```

It will hang waiting on stdin — that means it's working. Paste the line below and press Enter:

```
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}
```

You should see the JSON response above. Press `Ctrl+C` to exit.

## Troubleshooting

**"Couldn't reach MCP server" in Claude.ai**
- Re-add the connector — go to Settings → Connectors, remove the existing entry, and add it again
- Make sure the OAuth flow completed fully (you were redirected back to Claude.ai after logging in)
- Try the curl verification command above to confirm the server is reachable

**npx fails with `command not found` or exits silently**
- Confirm Node.js 18+ is installed: `node --version`
- Confirm `DEVOPSAGENT_API_KEY` is set — if missing, the bridge exits immediately with an error on stderr
- Try with an explicit version: `npx -y @devopsagent/mcp-server@latest`
- Clear the npx cache and retry: `npm cache clean --force`

**Tools not appearing in Claude Desktop**
- Fully quit Claude Desktop (check system tray / menu bar) and reopen — a window close is not enough
- Check the config file path is correct for your OS (Windows vs macOS differ)
- Validate your JSON is well-formed — a single missing comma breaks the whole config

**401 Unauthorized errors**
- The API key must be created at devopsagent.io/settings (keys prefixed `doa_live_` are valid)
- Keys are per-user — make sure you're logged into the right account when generating

**`tools_loaded` shows an unexpected number**
- The server exposes 704 tools across 13 modules — this is the correct count
- If you see a different number, the server may be mid-deploy; retry after a minute

## Tools

| Module | Count | What you can do |
|--------|-------|-----------------|
| AWS | 352 | EC2, S3, RDS, Lambda, ECS, EKS, IAM, VPC, CloudWatch, DynamoDB, and more |
| Kubernetes | 76 | Pods, Deployments, Services, Namespaces, Ingress, Jobs, Nodes |
| Azure | 38 | VMs, Storage, SQL, NSGs, Container Instances, VNets, Public IPs |
| GCP | 42 | Compute, GCS, Cloud SQL, GKE, Cloud Run, Pub/Sub, BigQuery, Functions |
| CI/CD | 36 | Jenkins, GitHub Actions and GitLab |
| Docker | 22 | Containers, images, volumes, networks, compose, build, push |
| Terraform | 26 | init, plan, apply, destroy, state, workspaces, import |
| Ansible | 13 | Playbooks, ad-hoc, inventory, vault, galaxy |
| Monitoring | 12 | Prometheus, Datadog, Grafana |
| Alerting | 16 | PagerDuty + OpsGenie |
| SonarQube | 12 | Projects, quality gates, issues, analysis |
| Nexus | 12 | Repositories, components, assets |
| Git | 47 | Clone, branch, commit, push, pull, merge, rebase, tags, stash, search |

## Approvals and connected tools

- **Risky actions wait for approval.** Deletes, terminations, firewall and IAM changes and other
  medium/high-risk tools don't run straight away. The call returns `isError: true` with an
  `approval_id` and a message saying who confirms it: your organization's owner or admin, or
  you yourself at [devopsagent.io/approvals/mine](https://devopsagent.io/approvals/mine) if no
  one else can. Run the tool again once it is approved.
- **CI/CD, alerting, monitoring and code-quality tools use your own connections.** Connect
  GitHub, GitLab, Jenkins, PagerDuty, OpsGenie, Datadog, SonarQube or Nexus under
  **Settings → Integrations** at devopsagent.io. Without one, those tools say so instead of
  running.
- **Cloud tools use the AWS, Azure or GCP account you connected** under
  **Settings → Cloud Credentials**. If AWS refuses an action, the tool returns AWS's error; the
  in-app chat can turn that into a permission request, MCP calls can't yet.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DEVOPSAGENT_API_KEY` | Yes | — | API key from devopsagent.io Settings → API Keys |
| `DEVOPSAGENT_MCP_URL` | No | `https://devopsagent.io/mcp/` | Override endpoint (self-hosted instances only) |

## Server Details

| Property | Value |
|----------|-------|
| MCP Protocol | `2025-03-26` |
| Transports | Streamable HTTP (`POST /mcp/`) + HTTP+SSE (`GET /mcp/sse`) + stdio (via `npx`) |
| Auth | OAuth 2.0 (Claude.ai) or API Key (Claude Desktop / npx) |
| Registry | `io.github.shittuay/devops-agent` |
| Health check | `GET https://devopsagent.io/mcp/health` |

## Links

- **Website:** [devopsagent.io](https://devopsagent.io)
- **API Keys:** [devopsagent.io/settings](https://devopsagent.io/settings)
- **GitHub:** [github.com/shittuay/DevOps-Agent](https://github.com/shittuay/DevOps-Agent)
- **npm:** [@devopsagent/mcp-server](https://www.npmjs.com/package/@devopsagent/mcp-server)
