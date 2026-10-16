# MCP Registry Submission - DevOps Agent

This document contains all the information needed to submit DevOps Agent to the Anthropic MCP Registry.

## Registry Entry

Create `servers/devops-agent.json` in the `github.com/anthropics/mcp` repository:

```json
{
  "name": "devops-agent",
  "display_name": "DevOps Agent",
  "description": "Manage AWS, Azure, GCP, Kubernetes, CI/CD, Docker, Terraform and more. 704 tools across 13 modules including monitoring and alerting.",
  "server_json_url": "https://devopsagent.io/mcp/server.json",
  "website_url": "https://devopsagent.io",
  "categories": [
    "cloud",
    "infrastructure",
    "devops",
    "aws",
    "kubernetes",
    "docker",
    "terraform",
    "ci/cd",
    "monitoring"
  ]
}
```

## Server Manifest

The `server.json` manifest is available at:
- **URL**: https://devopsagent.io/mcp/server.json
- **Schema**: https://static.modelcontextprotocol.io/schemas/2025-10-17/server.schema.json

Key details:
- **Name**: `io.github.shittuay/devops-agent` (reverse-DNS format)
- **Version**: 1.0.7
- **Title**: DevOps Agent
- **Description**: Manage AWS, Azure, GCP, Kubernetes, CI/CD, Docker, Terraform and more. 704 tools.
- **Website**: https://devopsagent.io
- **Repository**: https://github.com/shittuay/DevOps-Agent

## OAuth 2.0 + PKCE Configuration

The MCP server uses OAuth 2.0 with PKCE for secure authentication.

### Authorization Server Metadata (RFC 8414)

```bash
curl https://devopsagent.io/.well-known/oauth-authorization-server
```

Returns:
```json
{
  "issuer": "https://devopsagent.io",
  "authorization_endpoint": "https://devopsagent.io/mcp/oauth/authorize",
  "token_endpoint": "https://devopsagent.io/mcp/oauth/token",
  "response_types_supported": ["code"],
  "grant_types_supported": ["authorization_code"],
  "code_challenge_methods_supported": ["S256"],
  "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
  "scopes_supported": ["mcp"]
}
```

### Protected Resource Metadata (RFC 9728)

```bash
curl https://devopsagent.io/.well-known/oauth-protected-resource
```

Returns:
```json
{
  "resource": "https://devopsagent.io/mcp",
  "authorization_servers": ["https://devopsagent.io"],
  "bearer_methods_supported": ["header", "query"],
  "scopes_supported": ["mcp"]
}
```

## Transport Endpoints

- **Streamable HTTP**: https://devopsagent.io/mcp/
- **SSE (Legacy)**: https://devopsagent.io/mcp/sse
- **Health Check**: https://devopsagent.io/mcp/health

## Tools Overview (704 total across 13 modules)

| Module | Tool Count | Key Capabilities |
|--------|------------|------------------|
| AWS | 352 | EC2, VPC, IAM, RDS, Lambda, ECS, EKS, S3, DynamoDB, CloudFormation, etc. |
| Kubernetes | 76 | Pods, Deployments, Services, Namespaces, ConfigMaps, Secrets, Jobs |
| Azure | 38 | VMs, Storage, SQL, NSGs, Container Instances, Disks, VNets |
| GCP | 42 | Compute, GCS, Cloud SQL, GKE, Cloud Run, Pub/Sub, BigQuery |
| CI/CD | 36 | Jenkins, GitHub Actions, GitLab CI |
| Terraform | 26 | init, plan, apply, destroy, workspace, state management, import |
| SonarQube | 12 | Code quality, projects, issues, quality gates |
| Nexus | 12 | Repositories, components, cleanup tasks |
| Docker | 22 | Containers, images, volumes, networks, compose |
| Git | 47 | Repository setup, branching, staging, committing, remote ops, tags, stashing, search, maintenance |
| Monitoring | 12 | Prometheus, Datadog, Grafana |
| Ansible | 13 | Playbooks, ad-hoc commands, inventory, vault |
| Alerting | 16 | PagerDuty + OpsGenie incidents/alerts |

## NPM Package (stdio bridge)

For Claude Desktop users who prefer stdio transport:

```bash
npx @devopsagent/mcp-server
```

Package details:
- **Name**: `@devopsagent/mcp-server`
- **Version**: 1.0.7
- **Registry**: npm
- **Transport**: stdio
- **Repository**: https://github.com/shittuay/DevOps-Agent/tree/main/mcp/npm-package

## Icons

Light and dark mode icons (128x128 PNG):
- **Light**: https://devopsagent.io/static/icons/mcp-icon-light.png
- **Dark**: https://devopsagent.io/static/icons/mcp-icon-dark.png

SVG source available at: `static/icons/mcp-icon.svg`

## Authentication Flow

1. User clicks "Connect" in Claude.ai
2. Redirected to `https://devopsagent.io/mcp/oauth/authorize`
3. User signs in with email/password
4. Authorization code returned to Claude.ai with PKCE
5. Claude.ai exchanges code for access token at `/mcp/oauth/token`
6. Access token valid for 30 days (stored in memory)

## Testing Commands

```bash
# Health check (no auth required)
curl https://devopsagent.io/mcp/health

# Test OAuth metadata
curl https://devopsagent.io/.well-known/oauth-authorization-server
curl https://devopsagent.io/.well-known/oauth-protected-resource

# Test with valid token
curl -s https://devopsagent.io/mcp/ \
  -H "Authorization: Bearer TEST_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# List tools via SSE transport
curl -H "Authorization: Bearer TEST_TOKEN" \
  https://devopsagent.io/mcp/sse
```

## PR Description Template

```markdown
## DevOps Agent MCP Server

DevOps Agent is a comprehensive infrastructure management platform that exposes 704 tools across 13 modules as an MCP-compliant remote server.

### What's included
- **704 tools** across AWS, Azure, GCP, Kubernetes, CI/CD, Docker, Terraform, SonarQube, Nexus, monitoring, and alerting
- **OAuth 2.0 + PKCE** authentication with RFC 8414/9728 compliant discovery endpoints
- **Streamable HTTP** and **SSE** transports
- **npm package** `@devopsagent/mcp-server` for stdio bridge support
- **Health endpoint** at `/mcp/health` for load balancer checks

### Server JSON
https://devopsagent.io/mcp/server.json

### Website
https://devopsagent.io

### Categories
cloud, infrastructure, devops, aws, kubernetes, docker, terraform

### Testing
I can provide test credentials for Anthropic's validation team if needed.
```

## Files Changed for This Submission

1. `mcp/server.json` - Added `icons` and `packages` sections
2. `static/icons/README.md` - Documentation for icon assets
3. `static/icons/mcp-icon.svg` - Source SVG for icon generation

## Next Steps

1. Fork `github.com/anthropics/mcp`
2. Create `servers/devops-agent.json` with the registry entry above
3. Submit PR using the description template
4. Respond to any review feedback from Anthropic team
5. Once merged, DevOps Agent will appear in Claude.ai's connector directory

## Contact

- **Maintainer**: shittuay
- **Repository**: https://github.com/shittuay/DevOps-Agent
- **Issues**: https://github.com/shittuay/DevOps-Agent/issues
