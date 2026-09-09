# DevOps Agent — Knowledge Vault

Obsidian vault used as long-term project memory for Claude Code sessions.
Read this index first, then follow only the links relevant to the current task.

**Division of labor** (don't duplicate):
- `CLAUDE.md` — how the codebase works today (architecture, patterns, checklists)
- `CLAUDE_RUNBOOK.md` — historical bug fixes
- `WORKLOG.md` (via `/memory` skill) — session-to-session work state
- **This vault** — *why* things are the way they are: decisions, postmortems, design rationale

## Decisions
- [[pin-requirements-exactly]] — why requirements.txt is fully ==-pinned (2026-07-15, PR #50)
- [[ssm-deploy-no-ssh]] — why deploys go through AWS SSM instead of inbound SSH
- [[service-reachability-probes]] — http_check/tcp_check + "a 404 is not success" prompt rules (2026-09-09)

## Debugging / Postmortems
- [[coverage-7-15-1-ci-outage]] — loose `coverage>=` pin took CI down Jul 13–15, 2026

## Architecture
_(rationale notes go here — e.g. why guardrails fail open, why SSRF guard allows RFC1918)_

## Conventions for new notes
- One decision/incident per file, in the matching subfolder
- Frontmatter: `date` (absolute, YYYY-MM-DD), `type` (decision | postmortem | rationale), `tags`
- Link related notes with `[[wikilinks]]` and add a line to this index
