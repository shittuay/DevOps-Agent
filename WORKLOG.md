# DevOps Agent - Work Log

> Auto-maintained by Claude Code `/memory` skill. Last updated: 2026-02-11

## Current State
- **Last Session:** 2026-02-11 - Fixed deploy crash loop (init_secrets non-fatal + PM2 ecosystem config)
- **Deploy Status:** Deploying to devopsagent.io
- **Branch:** main
- **Uncommitted Work:** No

## Recent Changes (last 5 sessions)

### 2026-02-11 - Fix deploy crash loop + PM2 ecosystem config
- What was done:
  - ROOT CAUSE: `init_secrets()` raised `RuntimeError` on any AWS failure, crashing the app. PM2 restarted it in a loop (11 restarts). New code never served.
  - Made `init_secrets()` non-fatal: returns `True/False` instead of raising exceptions
  - Added .env fallback in app.py: if AWS Secrets Manager fails, loads `config/.env` as backup
  - Fixed `.env` file having leading whitespace from YAML heredoc indentation (added `sed` strip)
  - Switched deploy from `pm2 start app.py --interpreter` to PM2 ecosystem config (`ecosystem.config.js`) for persistent env vars across restarts
  - Added `pm2 logs` output to deploy script for debugging visibility
  - Added `max_restarts: 5` and `restart_delay: 5000` to prevent infinite crash loops
  - Bumped health endpoint version to `2026-02-11-v5`
- Files changed: services/secrets_manager.py, app.py, .github/workflows/deploy.yml

### 2026-02-11 - Fix Stripe lazy-loading + diagnostic endpoint
- What was done:
  - ROOT CAUSE FIX: `stripe_integration.py` was reading env vars at import time (module level). If AWS Secrets Manager hadn't loaded yet, all Stripe config was `None` forever. Refactored to read env vars lazily at call time.
  - Added `_ensure_stripe_configured()` guard before every Stripe API call
  - Added `/api/stripe/status` diagnostic endpoint (login required) - shows which Stripe env vars are set without exposing values
  - Fixed `BASE_URL` in deploy workflow from `http://34.239.157.235:5000` to `https://devopsagent.io`
  - Added detailed debug logging to checkout endpoint
  - Improved JS error handling to show actual server errors in toast
  - User confirmed all Stripe secrets added to AWS Secrets Manager
  - User set up Stripe webhook endpoint at `https://devopsagent.io/api/stripe/webhook`
- Files changed: stripe_integration.py, app.py, templates/billing.html, .github/workflows/deploy.yml
- Deployed: Yes (auto-deploy running)
- Commits: `79b18b4` (debug logging + BASE_URL), `76a4c20` (lazy-load fix + diagnostic)

### 2026-02-11 - Fix billing payment bypass + font sizes
- What was done:
  - Disabled legacy endpoints `/api/subscription/upgrade` and `/api/credits/purchase` that granted free credits without Stripe payment (security fix)
  - Added missing Stripe price IDs to `MANAGED_SECRET_KEYS` in `secrets_manager.py` so they load in production
  - Fixed billing page credit pack sizes to match Stripe config (100/250/500/1000)
  - Bumped 10-11px fonts to 13px and 12px to 14px across 6 templates (88 total fixes)
  - Created `/update-context`, `/resume-work`, and `/memory` skills
  - Updated CLAUDE.md with billing flow docs and resolved issues
- Files changed: app.py, services/secrets_manager.py, templates/billing.html, templates/index.html, templates/dashboard_live.html, templates/changes.html, templates/compliance/dashboard.html, templates/templates.html, CLAUDE.md, .claude/skills/
- Deployed: Yes
- Commits: `fe62cdb` (billing fix), `b935f60` (font sizes), `bcf24f0` (memory skill)

### 2026-02-11 - Wire billing to Stripe Checkout
- What was done: Updated billing.html JS to call Stripe Checkout endpoints instead of legacy free-upgrade endpoints
- Commit: `2aa4a42`

## Pending / In Progress
- [ ] VERIFY: Stripe Checkout redirect working after lazy-load fix (user to test when awake)
- [ ] User can check config at: https://devopsagent.io/api/stripe/status (must be logged in)
- [ ] Fix pre-existing test failures (18 tests failing due to outdated test fixtures)
- [ ] GitHub Dependabot alert: 1 high vulnerability in cryptography package

## Important Decisions
- 2026-02-11: Legacy billing endpoints disabled (return 403) rather than deleted. Credits only via Stripe webhook.
- 2026-02-11: Minimum font size policy: no fonts below 13px in templates.
- 2026-02-11: Stripe env vars now read lazily at call time, not at import time. This prevents timing issues with AWS Secrets Manager.

## Known Issues
- 18 pre-existing test failures in test_api.py and test_auth.py (route changes not reflected in tests)
- If Stripe still doesn't work, check `/api/stripe/status` endpoint to see which env vars are missing

## User Preferences
- Deploy flow: commit -> push -> auto-deploy via GitHub Actions to EC2
- Production URL: devopsagent.io (EC2 at 34.239.157.235:5000)
- No emojis unless requested
- Prefers fast iteration: test, commit, push, deploy in one flow
- Note: User mentioned `--dangerously-skip` - may want to skip pre-commit hooks or confirmations for speed
