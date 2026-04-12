# Changelog

All notable changes to `@devopsagent/mcp-server` are documented here.

## [1.0.6] - 2026-04-12

### Changed
- Updated tool count to 727 (Git tools expanded 6 → 47, GitHub tools 18 → 19)
- Security: removed leaked review credentials from git history, rotated all secrets
- Review credentials now stored in AWS Secrets Manager (never in repo)

## [1.0.4] - 2026-04-07

### Changed
- Corrected tool count to 685 across all docs (README, package.json, server.json)
- `devopsagent_health` now reports accurate `tools_loaded` using deduplicated map count
- Updated per-module counts: AWS 334, Kubernetes 76, Azure 38, GCP 42, CI/CD 35, Terraform 25

## [1.0.3] - 2026-04-07

### Fixed
- Add `mcp-server` bin entry so `npx @devopsagent/mcp-server` resolves correctly on all platforms (npx looks for a bin matching the unscoped package name)

## [1.0.2] - 2026-04-07

### Added
- `bin/server.js` — Node.js stdio bridge; `npx @devopsagent/mcp-server` now works
- `bin` entry in `package.json` (`devopsagent-mcp` command)
- `files` field in `package.json` to control published package contents
- `CHANGELOG.md`
- `devopsagent_health` built-in tool on the Python server (no credentials required)
- Expanded `keywords` in `package.json` for better npm discoverability

### Changed
- README rewritten: npx quickstart is now the primary connection method
- Server version bumped to `1.0.2` in both `server.json` and Python server
- Tool execution errors now returned as MCP `isError: true` content instead of JSON-RPC error objects (better client compatibility)

## [1.0.1] - 2026-04-05

### Changed
- `server.json` schema updated to `2025-10-17`
- Added `mcpName` field (`io.github.shittuay/devops-agent`) for MCP registry

## [1.0.0] - 2026-04-04

### Added
- Initial publish to npm
- MCP registry manifest (`server.json`)
- Streamable HTTP transport (`POST /mcp/`)
- HTTP+SSE transport (`GET /mcp/sse`)
- OAuth 2.0 authorization flow for Claude.ai connectors
- 401 tools across 13 modules (AWS, Kubernetes, Azure, GCP, CI/CD, Docker, Terraform, Ansible, Monitoring, Alerting, SonarQube, Nexus, Git)
