# DevOps Agent — Engineering Handover

**Repo:** `shittuay/DevOps-Agent` · **Default branch:** `main` · **Last updated:** 2026-06-10

This document is a point-in-time handover of recent automation/auth work and the
operational context needed to continue it. For durable architecture reference see
[CLAUDE.md](CLAUDE.md); for historical fixes see
[CLAUDE_RUNBOOK.md](CLAUDE_RUNBOOK.md).

## 1. Recently shipped (merged to `main`)

| PR | Title | Status |
|----|-------|--------|
| #31 | Routine docs Stop hook + daily security scan (+ test/doc accuracy fixes) | Merged |
| #32 | Fix email/phone MFA: load delivery config from AWS Secrets Manager | Merged |

Both feature branches were auto-deleted on merge (expected) — the code lives on
`main`, not on any branch.

## 2. Automation added

### a) Docs-sync Stop hook
- `scripts/hooks/docs_update_check.py`, registered in `.claude/settings.json` (`Stop`).
- Fires at the end of a Claude Code turn. If source files (`.py/.html/.js/.css/.yaml/.yml`)
  changed but no `.md` did, it blocks the stop and requests a docs update.
- Guards: ignores `tests/`, `scripts/hooks/`, `.claude/`, `logs/`, `.playwright-mcp/`;
  honors `stop_hook_active` (nudges once); skips untracked (`??`) files; fails open on
  git errors; `DOCS_HOOK_DISABLE=1` bypasses. Only affects Claude Code sessions.

### b) Daily security scan
- `.github/workflows/security-scan.yml` — cron `0 6 * * *` (06:00 UTC) + `workflow_dispatch`.
- Runs `pip-audit`, `safety`, `bandit`; uploads `scheduled-bandit-report` (30-day
  retention); each step `continue-on-error`. Runs on schedule now that it is on `main`.

### c) Test/doc accuracy
- `tests/conftest.py` `collect_ignore` excludes the live-API diagnostic scripts
  `test_stripe.py` and `test_secrets_manager.py` (they call live Stripe/AWS and asserted
  nothing). Suite is **404 passing** on SQLite in-memory.

## 3. MFA fix — code merged, INFRA STEP STILL REQUIRED

**Symptom:** email and phone (SMS) sign-in codes fail; authenticator-app (TOTP) works.

**Cause:** TOTP is computed locally (no delivery). Email/SMS need a provider whose config
reaches the app via `init_secrets()`, which only loads keys in `MANAGED_SECRET_KEYS`
(`services/secrets_manager.py`). Those keys were missing, so the app fell back to Brevo's
SMTP relay host (rejecting a non-Brevo SMTP key); SMS had no managed provider key at all.

**Code fix (merged):** added `EMAIL_PROVIDER`, `SMTP_HOST`, `SMTP_PORT`, `EMAIL_FROM`,
`EMAIL_FROM_NAME`, `SENDGRID_API_KEY`, `BREVO_API_KEY`, `SMS_SENDER_NAME` to
`MANAGED_SECRET_KEYS`.

**Remaining operator action (outside the repo — highest-priority open item):**
1. Add to the `devops-agent/production` Secrets Manager JSON: `EMAIL_PROVIDER=smtp`,
   `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `EMAIL_FROM` — plus `BREVO_API_KEY`
   for phone/SMS.
2. Run with `FLASK_ENV=production` (or `USE_AWS_SECRETS=true`) and restart.
3. Test an email login. On failure, `email_service`/`sms_service` now log the exact
   provider error.

Until step 1 is done, users still see "Failed to send verification email/SMS code."

## 4. Open items (none blocking)

1. **Populate the MFA secret** (section 3) — do first.
2. **Branch sprawl** — ~18 stale `claude/*` remote branches; the merged ones are safe to
   prune (owner's call — destructive, left untouched).
3. **Optional hardening:** add a startup config-validation for email/SMS mirroring the
   Stripe check (`app.py:31-55`) so misconfig is caught at boot, not at first login.
4. **Cloudflare "Workers Builds" check** — external, always-red on PRs. This Flask app
   cannot run on Cloudflare Workers (Postgres, WebSockets, C-extensions, SDK bundle size).
   If it is a required check it blocks merges; fix in the Cloudflare dashboard, not the
   repo. Deferred by the owner.

## 5. Environment gotchas

- **Install into a venv** (`python -m venv .venv`) — system Python hits a Debian setuptools
  bug on `multi-key-dict`. Tests use SQLite in-memory; Postgres not required.
- **Permission rules:** Bash commands containing the substring `secret` are denied; some
  multi-line commit messages and compound `&&` commands are blocked. Stage with
  `git add -u`, use single-line commit messages, avoid `secret` in branch names.
- **GitHub access** is via `mcp__github__*` tools only, scoped to this repo (no `gh` CLI).
- **Never push to `main`** — land work on a branch + PR.
