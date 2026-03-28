# DevOps Agent - Work Log

> Auto-maintained by Claude Code `/memory` skill. Last updated: 2026-03-26

## Current State
- **Last Session:** 2026-03-26 - Flask app context fix for chat streaming
- **Deploy Status:** Production at devopsagent.io (EC2 34.239.157.235)
- **Branch:** main (clean, up to date with origin)
- **Uncommitted Work:** No

## Recent Changes (last 5 sessions)

### 2026-03-26 - Flask app context + credential fixes
- What was done: Fixed Flask app context not preserved through SSE chat stream (stream_with_context). Fixed credentials display issue. Surfaced real AWS credential errors instead of generic messages. Fixed QA issues: signup password confirmation, public model health endpoint. Injected cloud credential status into agent system prompt.
- Files changed: app.py, src/agent/core.py, services/credential_service.py
- Deployed: Yes (auto-deploy)
- Commits: `8c44156`, `8937499`, `3bc45a2`, `8766321`, `38d6dc0`

### 2026-03-20 - Status page + Brevo integration
- What was done: Status page live at status.devopsagent.io. Brevo subscribe/notify flow added. `/api/status/health` endpoint created. Planned: transactional emails + Brevo marketing campaign for first 50-100 customers.
- Deployed: Yes

### 2026-03-18 - Quiz hardening + UI tweaks
- What was done: Quiz hardening committed. `>_` logo added to login page. Theme toggle moved inline. Voice button added to input bar. Curriculum redesign was built then reverted (user didn't like it).
- Deployed: Yes

### 2026-03-16 - P3 TODOs + CI/CD + auth fixes
- What was done: All P3 TODOs completed. CI/CD fixed with Elastic IP 3.216.127.206. Resend-verification 404 fixed. TOTP→email-verify loop fixed.
- Deployed: Yes

### 2026-02-16 - OpenClaw feature port (10 features)
- What was done: input sanitizer, secret detector, /doctor diagnostics, SSE streaming, scheduled infra checks, webhook-triggered actions, multi-model failover, onboarding wizard, memory/context persistence, Docker sandboxing
- Deployed: Yes

## Pending / In Progress
- [ ] Transactional emails (post-2026-03-20 next step)
- [ ] Brevo marketing campaign for first 50-100 customers
- [ ] Fix pre-existing test failures (18 tests, outdated fixtures)

## Important Decisions
- 2026-02-11: Legacy billing endpoints disabled (return 403). Credits only via Stripe webhook.
- 2026-02-11: Stripe env vars read lazily at call time (not import time) to avoid timing issues.
- 2026-03-18: Curriculum redesign reverted — user preferred the original layout.

## Known Issues
- 18 pre-existing test failures in test_api.py and test_auth.py (route changes not reflected in tests)
- If Stripe still doesn't work, check `/api/stripe/status` endpoint to see which env vars are missing

## User Preferences
- Deploy flow: commit -> push -> auto-deploy via GitHub Actions to EC2
- Production URL: devopsagent.io (EC2 at 34.239.157.235)
- No emojis unless requested
- Always run git add/commit/push without asking for confirmation
- Prefers fast iteration: test, commit, push, deploy in one flow
