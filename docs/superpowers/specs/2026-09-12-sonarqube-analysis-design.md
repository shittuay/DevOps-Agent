# SonarQube static analysis and remediation

**Date:** 2026-09-12
**Status:** approved

## Goal

Stand up a SonarQube server on Docker Desktop, analyse the DevOps Agent
codebase, and fix the findings that matter — security vulnerabilities, bugs, and
genuine code duplication — while triaging the rest into a ranked backlog.

## Context

The repo has never been through Sonar. It contains roughly 121k lines of Python
across 267 files (97 of them tests), ~19 first-party JavaScript files, 103 Jinja
templates, and 99 stylesheets.

Two facts shaped the design:

1. **366 of the 385 tracked `.js` files live in `cli/node_modules`** — vendored
   third-party code committed to the repo. Analysing it would bury first-party
   findings at roughly 20:1, so it is excluded.
2. **This is production infrastructure code with documented security
   invariants.** CLAUDE.md records deliberate duplication (the four-step
   guardrails pipeline is hand-copied at eight call sites), deliberate
   opt-in guards (`_reject_flag_like`, `assert_safe_url`), and a risk
   classification table in `safety.py` whose exact membership is load-bearing.
   Sonar knows none of this and will recommend changes that break it.

## Decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Fix scope | Vulnerabilities, Security Hotspots, Bugs, and real duplication. Code Smells triaged; only high-severity ones fixed. | Keeps the diff reviewable and avoids churning security-critical files for style points. |
| Permanence | Committed local dev stack **plus** a SonarCloud CI gate. | Any dev can re-scan; PRs get an automated gate. |
| Database | Dedicated Postgres container. | SonarQube's embedded H2 is unsupported for persistence; history would be lost between runs. |
| Scanner | Dockerised `sonar-scanner-cli`. | No JDK install on Windows. |
| CI gate | SonarCloud with the default **Clean as You Code** gate. | Only *new* code must be clean, so the existing 121k lines become a legacy baseline instead of failing every PR with a five-figure backlog. |

## Architecture

`docker-compose.sonar.yml`, kept separate from `docker-compose.yml` so the
analysis stack starts and stops without touching the app stack, and so the two
Postgres services never collide.

- `sonar-db` — `postgres:16-alpine`, **no host port**, reachable only over the
  compose network.
- `sonarqube` — `sonarqube:community` on `localhost:9000`, with named volumes for
  `data`, `logs`, and `extensions`.
- `sonar-scanner` — `sonarsource/sonar-scanner-cli` behind a `scan` Compose
  profile so `up -d` never starts it.

`scripts/sonar-scan.sh` wraps the workflow: preflight, wait for `status=UP`,
bootstrap credentials, scan.

### Credential bootstrap

The script ships no hardcoded password. On first run it generates a random
policy-compliant admin password, rotates SonarQube's `admin/admin` default, mints
an analysis token through `/api/user_tokens/generate`, and writes both to
`.sonar-token` with `umask 077`. The file is gitignored; later runs source it.

### Analysis scope

`sonar.sources=.` with an exclusion list, rather than an allowlist of
directories, so a new top-level package is analysed automatically instead of
silently going unscanned. `tests/` is registered as test sources so test-only
patterns do not inflate the production smell count, and `sonar.cpd.exclusions`
skips test duplication, which is usually deliberate.

`.coveragerc` mirrors `sonar.exclusions` so the imported coverage ratio is
measured over the same file set Sonar analyses.

## Remediation loop

Findings are pulled from the SonarQube web API, grouped by rule and file, and
fixed one theme per batch. `pytest -q` runs after every batch — the 497-test
suite is the regression net — and each theme lands as its own commit. A final
re-scan proves the delta.

### Invariant guard

Findings touching these are **reported, never auto-fixed**:

- `src/agent/safety.py` risk-classification sets
- The guardrails pipeline call sites (`app.py`, `routes/api_gateway.py`,
  `api/v1/conversations.py`, `routes/curriculum.py`)
- `_reject_flag_like` call sites in `src/tools/git_tools.py`
- `assert_safe_url` / `safe_request` call sites and their `# ssrf-safe:` exemptions
- `routes/auth.py` timing-safe password helpers

Sonar will flag the duplicated guardrails pipeline. CLAUDE.md explicitly defers
consolidating it as work that "warrants its own reviewed change rather than a
drive-by edit," so this design honours that.

## CI gate

A `sonarcloud` job in `.github/workflows/ci.yml`, running on pull requests and
pushes to `main`. It skips cleanly when `SONAR_TOKEN` is unset, and is
deliberately **not** added to `status-check`'s `needs`, so a SonarCloud outage
cannot block a deploy. Promoting it to a hard gate is a one-line change.

Requires manual setup outside this repo: create the SonarCloud organisation and
project, then add `SONAR_TOKEN` to GitHub secrets.

## Out of scope

- Consolidating the guardrails pipeline into a shared helper.
- Fixing low- and medium-severity code smells.
- Replacing existing lint tooling (`bandit`, `pip-audit`, `safety` stay as-is).
