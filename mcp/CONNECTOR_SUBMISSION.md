# Claude.ai Connector Submission — DevOps Agent

## Submission Form
https://docs.google.com/forms/d/e/1FAIpQLSeafJF2NDI7oYx1r8o0ycivCSVLNq92Mpc1FPxMKSw1CzDkqA/viewform

## Server Details

- **Server Name:** DevOps Agent
- **Description:** Manage AWS, Azure, GCP, Kubernetes, CI/CD, Docker, Terraform and more from Claude. 702 tools across 13 modules including monitoring and alerting.
- **Integration URL:** `https://devopsagent.io/mcp/`
- **SSE Endpoint:** `https://devopsagent.io/mcp/sse`
- **Health Check:** `https://devopsagent.io/mcp/health`
- **MCP Protocol Version:** 2025-03-26
- **Authentication:** OAuth 2.0 (Authorization Code + PKCE)

## Required Links

| Requirement | URL |
|---|---|
| Website | https://devopsagent.io |
| Documentation | https://github.com/shittuay/DevOps-Agent/blob/main/mcp/README.md |
| Privacy Policy | https://devopsagent.io/privacy-policy |
| Terms of Service | https://devopsagent.io/usage-policy |
| Support / Issues | https://github.com/shittuay/DevOps-Agent/issues |
| npm Package | https://www.npmjs.com/package/@devopsagent/mcp-server |
| MCP Registry | https://registry.modelcontextprotocol.io (name: io.github.shittuay/devops-agent) |

## Test Account for Reviewers

Credentials shared privately with the review team (never commit secrets to git).
- **OAuth URL:** https://devopsagent.io/mcp/oauth/authorize

## 3 Working Usage Examples

### Example 1: List EC2 Instances
**Prompt:** "Show me all EC2 instances in us-east-1"
**Tool called:** `list_ec2_instances`
**What happens:** Returns a JSON list of all EC2 instances with their IDs, types, states, and tags. Read-only operation, no side effects.

### Example 2: Check Kubernetes Pod Health
**Prompt:** "Are there any pods in CrashLoopBackOff in the production namespace?"
**Tool called:** `list_pods` with namespace=production
**What happens:** Lists all pods with their status. The agent identifies any unhealthy pods and explains the issue. Read-only.

### Example 3: Terraform Plan Review
**Prompt:** "Run terraform plan in /infrastructure and tell me what would change"
**Tool called:** `terraform_plan` with working_dir=/infrastructure
**What happens:** Executes `terraform plan` and returns the planned changes. The agent summarizes additions, modifications, and deletions. Read-only (plan does not apply changes).

## Safety Annotations

All 702 tools have MCP safety annotations:
- **230 tools** marked `readOnlyHint: true` (list, get, describe operations)
- **114 tools** marked `destructiveHint: true` (delete, terminate operations)
- **299 tools** marked as mutating (create, update, medium-risk operations)
- **All tools** marked `openWorldHint: true` (interact with cloud APIs)

Destructive operations also go through the SafetyValidator which classifies risk levels and requires confirmation for high-risk actions.

## OAuth 2.0 Flow

1. Claude.ai redirects to `https://devopsagent.io/mcp/oauth/authorize`
2. User logs in with their devopsagent.io credentials
3. Server issues authorization code → redirects back to Claude.ai
4. Claude.ai exchanges code for access token at `https://devopsagent.io/mcp/oauth/token`
5. PKCE (S256) is supported

## Well-Known Endpoints

- `https://devopsagent.io/.well-known/oauth-protected-resource` — Resource metadata
- `https://devopsagent.io/.well-known/oauth-authorization-server` — Authorization server metadata

## Contact

- **Email:** support@devopsagent.io
- **GitHub:** https://github.com/shittuay/DevOps-Agent/issues
