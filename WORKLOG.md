# DevOps Agent - Work Log

> Auto-maintained by Claude Code `/memory` skill. Last updated: 2026-02-11

## Current State
- **Last Session:** 2026-02-11 - Fixed billing payment bypass, added skills, fixed font sizes
- **Deploy Status:** Deployed successfully to devopsagent.io (EC2 via GitHub Actions)
- **Branch:** main
- **Uncommitted Work:** No

## Recent Changes (last 5 sessions)

### 2026-02-11 - Fix billing payment bypass + font sizes
- What was done:
  - Disabled legacy endpoints `/api/subscription/upgrade` and `/api/credits/purchase` that granted free credits without Stripe payment (security fix)
  - Added missing Stripe price IDs to `MANAGED_SECRET_KEYS` in `secrets_manager.py` so they load in production
  - Fixed billing page credit pack sizes to match Stripe config (100/250/500/1000)
  - Bumped 10-11px fonts to 13px and 12px to 14px across 6 templates (88 total fixes)
  - Created `/update-context`, `/resume-work`, and `/memory` skills
  - Updated CLAUDE.md with billing flow docs and resolved issues
- Files changed: app.py, services/secrets_manager.py, templates/billing.html, templates/index.html, templates/dashboard_live.html, templates/changes.html, templates/compliance/dashboard.html, templates/templates.html, CLAUDE.md, .claude/skills/ (3 new skills)
- Deployed: Yes
- Commits: `fe62cdb` (billing fix), `b935f60` (font sizes)

### 2026-02-11 - Wire billing to Stripe Checkout
- What was done: Updated billing.html JS to call Stripe Checkout endpoints instead of legacy free-upgrade endpoints
- Commit: `2aa4a42`

### 2026-02-11 - Deploy workflow for new EC2
- What was done: Updated GitHub Actions deploy workflow for new Ubuntu EC2 instance
- Commit: `752c1a7`

## Pending / In Progress
- [ ] Add Stripe price IDs to AWS Secrets Manager (`devops-agent/production` JSON) - required for Stripe Checkout to work in production
- [ ] Verify Stripe webhook secret in AWS is real (not placeholder `whsec_your_webhook_secret_here`)
- [ ] Fix pre-existing test failures (18 tests failing due to outdated test fixtures, not related to recent changes)
- [ ] GitHub Dependabot alert: 1 high vulnerability in cryptography package

## Important Decisions
- 2026-02-11: Legacy billing endpoints disabled (return 403) rather than deleted, to avoid breaking any external references. Credits/subscriptions now only granted via Stripe webhook handler.
- 2026-02-11: Minimum font size policy: no fonts below 13px in templates. 10-11px bumped to 13px, 12px bumped to 14px.

## Known Issues
- Stripe Checkout will not redirect until Stripe price IDs are added to AWS Secrets Manager
- `STRIPE_PUBLISHABLE_KEY` in config/.env ends with `abcdefgh` which may be a placeholder
- 18 pre-existing test failures in test_api.py and test_auth.py (route changes not reflected in tests)

## User Preferences
- Deploy flow: commit -> push -> auto-deploy via GitHub Actions to EC2
- Production URL: devopsagent.io (EC2 at 34.239.157.235:5000)
- No emojis unless requested
- Prefers fast iteration: test, commit, push, deploy in one flow
