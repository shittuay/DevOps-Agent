# Claude.ai Connector Submission — DevOps Agent

## Where to submit
Developer portal: https://claude.ai/directory/manage → **Submit new** → **MCP connector**
(needs a paid Claude plan). Guide: https://claude.com/docs/connectors/building/submission.
Status and reviewer feedback appear in the same portal; escalations go to `mcp-review@anthropic.com`.

The old Google Form is closed ("[deprecated] MCP Directory Submission Form"). An April 2026
entry went to the MCPB Desktop Extensions form, which is for local servers and is also deprecated.

## Server Details

- **Server Name:** DevOps Agent
- **Description:** Manage AWS, Azure, GCP, Kubernetes, CI/CD, Docker, Terraform and more from Claude. 704 tools across 13 modules including monitoring and alerting.
- **Integration URL:** `https://devopsagent.io/mcp/`
- **SSE Endpoint:** `https://devopsagent.io/mcp/sse`
- **Health Check:** `https://devopsagent.io/mcp/health`
- **MCP Protocol Version:** 2025-03-26
- **Authentication:** OAuth 2.0 (Authorization Code + PKCE) with dynamic client registration (`/mcp/oauth/register`). In the portal's Authentication step choose **OAuth with dynamic client registration**.

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

Credentials go in the portal's **Test & launch** step, which only reviewers see (never commit secrets to git).
Use a dedicated account with Sandbox on and two-factor off, so reviewers aren't stopped at the code step.
- **OAuth URL:** https://devopsagent.io/mcp/oauth/authorize

## 3 Working Usage Examples

### Example 1: List EC2 Instances
**Prompt:** "Show me all EC2 instances in us-east-1"
**Tool called:** `get_ec2_instances` with region=us-east-1
**What happens:** Returns a JSON list of all EC2 instances with their IDs, types, states, and tags. Read-only operation, no side effects.

### Example 2: Check Kubernetes Pod Health
**Prompt:** "Are there any pods in CrashLoopBackOff in the production namespace?"
**Tool called:** `get_pods` with namespace=production
**What happens:** Lists all pods with their status. The agent identifies any unhealthy pods and explains the issue. Read-only.

### Example 3: Terraform Plan Review
**Prompt:** "Run terraform plan in /infrastructure and tell me what would change"
**Tool called:** `terraform_plan` with working_dir=/infrastructure
**What happens:** Executes `terraform plan` and returns the planned changes. The agent summarizes additions, modifications, and deletions. Read-only (plan does not apply changes).

## Safety Annotations

Every tool returned by `tools/list` has a `title` (on the tool and in `annotations`) plus
`readOnlyHint`, `destructiveHint` and `openWorldHint`, derived from the same risk
classification the agent uses (`routes/mcp.py`, `_to_mcp_tool`). The directory requires a
title and a read-only/destructive hint on every tool; `tests/test_mcp_tool_titles.py` checks it.

Risky calls also need approval before they run (see "Approvals and connected tools" in
`mcp/README.md`).

## OAuth 2.0 Flow

1. Claude.ai redirects to `https://devopsagent.io/mcp/oauth/authorize`
2. User logs in with their devopsagent.io credentials (and a two-factor code if the account has 2FA on)
3. Server issues authorization code → redirects back to Claude.ai
4. Claude.ai exchanges code for access token at `https://devopsagent.io/mcp/oauth/token`
5. PKCE (S256) is supported

## Well-Known Endpoints

- `https://devopsagent.io/.well-known/oauth-protected-resource` — Resource metadata
- `https://devopsagent.io/.well-known/oauth-authorization-server` — Authorization server metadata

## Contact

- **Email:** support@devopsagent.io
- **GitHub:** https://github.com/shittuay/DevOps-Agent/issues
