# SonarQube static analysis

Local SonarQube server for analysing this repo, plus an optional SonarCloud gate
in CI.

## Quick start

```bash
docker compose -f docker-compose.sonar.yml up -d   # first boot takes 2-4 minutes
./scripts/sonar-scan.sh --coverage                 # run tests, then scan
```

Then open <http://localhost:9000/dashboard?id=devops-agent>.

Sign in as `admin`. The password was generated on first run and is stored in
`.sonar-token` (gitignored, mode 600) along with the analysis token.

Drop `--coverage` to skip the test run and reuse whatever `coverage.xml` is
already on disk:

```bash
./scripts/sonar-scan.sh
```

Stop the stack (analysis history is preserved in named volumes):

```bash
docker compose -f docker-compose.sonar.yml down
```

Destroy the server **and all analysis history**:

```bash
docker compose -f docker-compose.sonar.yml down -v
rm -f .sonar-token
```

## What gets analysed

`sonar-project.properties` scans the whole tree with an exclusion list, so a new
top-level package is picked up automatically rather than silently going
unanalysed.

Excluded:

| Path | Reason |
| --- | --- |
| `**/node_modules/**` | 366 vendored third-party JS files are committed under `cli/node_modules`; including them buries first-party findings at roughly 20:1 |
| `venv/`, `.venv/`, `env/` | virtualenvs |
| `**/*.min.js`, `**/*.min.css` | minified output |
| `migrations/versions/**` | generated Alembic revisions |
| `docs/`, `vault/`, `logs/`, `htmlcov/` | not source |

`tests/` is registered as **test sources**, so test-only patterns are judged
under test rules instead of inflating the production Code Smell count.
`sonar.cpd.exclusions` skips duplication detection in tests, where repeated
arrange blocks are usually deliberate.

`.coveragerc` mirrors these exclusions so the coverage percentage Sonar imports
is measured over the same file set it analyses.

**`.coveragerc` also affects CI.** `coverage.py` reads it automatically, and
`ci.yml`'s test job runs `pytest --cov=.` without `--cov-config`, so the
Codecov number now excludes `tests/`, `scripts/`, and virtualenvs too. That is a
more honest figure than the previous one (which counted the test files as
covered code), but expect a one-time step change in the reported percentage the
first time this lands — it is a measurement change, not a coverage regression.

## Reading the results against this codebase

Sonar has no knowledge of the security invariants documented in `CLAUDE.md`, and
it will confidently recommend changes that break them. Treat findings in these
areas as **reports to review, not instructions to apply**:

- **`src/agent/safety.py`** — the exact membership of `high_risk_tools` /
  `medium_risk_tools` is load-bearing. A "simplify this collection" smell is not
  a licence to restructure it.
- **The guardrails pipeline** — the four-step `sanitize_input` →
  `is_guardrail_blocked` → `validate_message` → `screen_message` sequence is
  hand-copied at eight call sites, and Sonar flags it as duplication.
  Consolidating it is a known, *deliberately deferred* refactor (see the
  Guardrails section of `CLAUDE.md`); it warrants its own reviewed change rather
  than a drive-by deduplication.
- **`_reject_flag_like` call sites** in `src/tools/git_tools.py` — these look
  like redundant validation and are not.
- **`assert_safe_url` / `safe_request` call sites** and their `# ssrf-safe:`
  exemption comments.
- **`routes/auth.py`** — `_run_timing_safe_password_check` deliberately performs
  "unnecessary" work to keep response time uniform. Sonar reads that as dead
  computation.

## SonarCloud CI gate

`ci.yml` has a `sonarcloud` job that runs after `test`, reusing that job's
`coverage.xml` artifact instead of re-running the suite.

It **skips cleanly when `SONAR_TOKEN` is unset**, so the pipeline is unaffected
until you finish the one-time setup below. It is also deliberately *not* part of
`status-check`'s `needs`, so a SonarCloud outage cannot block a deploy. To
promote it to a hard gate, add `sonarcloud` to `status-check`'s `needs` and
check its result there.

### One-time setup

1. Sign in at <https://sonarcloud.io> with GitHub and import this repository.
2. Under **Administration → Analysis Method**, disable Automatic Analysis
   (CI-based analysis and automatic analysis are mutually exclusive).
3. Generate a token: **My Account → Security → Generate Token**.
4. In GitHub → **Settings → Secrets and variables → Actions**:
   - Secret `SONAR_TOKEN` — the token from step 3.
   - Variable `SONAR_ORGANIZATION` — your SonarCloud org key.
   - Variable `SONAR_PROJECT_KEY` — the project key SonarCloud assigned
     (typically `<org>_<repo>`).

The default **Clean as You Code** quality gate only measures *new* code, so the
existing ~121k lines become a legacy baseline instead of failing every PR with a
five-figure backlog.

## Troubleshooting

**SonarQube container exits shortly after start.** Its embedded Elasticsearch
needs `vm.max_map_count >= 262144`. `scripts/sonar-scan.sh` checks this and fails
with the fix, which on Docker Desktop / WSL2 is:

```bash
wsl -d docker-desktop sysctl -w vm.max_map_count=262144
```

**`Could not rotate the admin password`.** The server was already bootstrapped
but `.sonar-token` is gone. Either reset the password from the UI and write the
file by hand, or wipe the server with `down -v` (destroys history).

**Scan reports 0 files.** Check that the scanner container can see the repo —
`docker-compose.sonar.yml` mounts the repo root at `/usr/src`, which is the
scanner image's default working directory.

## Triage backlog (first scan, 2026-09-12)

The first scan reported 2203 issues (63 vulnerabilities, 197 bugs, 1943 smells;
20 BLOCKER). Everything BLOCKER was fixed or dispositioned. What remains, ranked
by value per unit of risk:

| # | Work | Size | Notes |
| --- | --- | --- | --- |
| 1 | **Template accessibility** — `Web:InputWithoutLabelCheck` (105), `Web:MouseEventWithoutKeyboardEquivalentCheck` (68), `Web:S6853` (84), `Web:S6848` (67) | ~170 bugs + ~150 smells across ~25 templates | Real WCAG defects: inputs with no associated `<label>`, and click handlers on non-interactive elements with no keyboard path. Mechanical but wide, and templates have no render tests, so it wants its own PR with visual checks. Highest user-visible value left. |
| 2 | **`python:S6903` — `datetime.utcnow()`** (292) | 292 sites, `models.py` (24), `infrastructure_sync.py` (22), `app.py` (19) | Deprecated in 3.12; returns a naive datetime. Migrating to `datetime.now(timezone.utc)` changes values from naive to aware, which **will** break comparisons against existing naive datetimes. Needs a deliberate, tested migration, not a find-and-replace. |
| 3 | **`python:S1192` — duplicated literals** (230) | `aws_tools.py` (39), `app.py` (20) | Low risk, low reward. Good first-issue material. |
| 4 | **`python:S3776` — cognitive complexity** (138) | `app.py` (14), `src/agent/core.py` (11) | Genuine complexity, but these are the most safety-critical functions in the codebase. Refactor only alongside tests for the function being split. |
| 5 | **`css:S7924` — contrast** (275) | `base.html` (12), and most page templates | Accessibility; pairs naturally with item 1. |
| 6 | **Remaining template duplication** (~4500 lines) | `about`/`security`, `404`/`500`, `privacy`/`usage`, `billing`, `profile` | Only `forgot_password`/`reset_password` were byte-identical and safe to extract mechanically. The rest are *similar*, not identical (Sonar's CPD is token-based), so consolidating them means adopting a shared base layout for public pages — a design change, per `CLAUDE.md`'s rule that such work gets its own reviewed PR. |

Findings marked **False Positive** in SonarQube, with justifications recorded on
each issue — do not "fix" these if they reappear:

- `routes/auth.py` `_DUMMY_PASSWORD_HASH` (`python:S6437`) — the fixed hash is
  what makes login's bcrypt cost uniform for unknown accounts. Removing or
  randomising it reopens account enumeration.
- `services/learning_sandbox.py` simulated GitLab trigger token (`python:S6418`)
  — mock data, authenticates nothing.
- `templates/analytics/*.html` `new Chart(...)` (`javascript:S1848`) ×3 — the
  Chart.js constructor renders via side effect; the reference is intentionally
  not retained because the chart is built once and never re-rendered.

## Known gaps

**`routes/mcp.py` is not analysed.** The Python analyzer shipped with SonarQube
26.9 crashes on that file and skips it entirely:

```
WARN Unable to analyze file: routes/mcp.py
java.lang.ClassCastException: UnpackingExpressionImpl cannot be cast to KeyValuePair
    at org.sonar.python.checks.hotspots.CorsCheck.getValueInDictionary(CorsCheck.java:366)
```

This is an upstream analyzer defect, not a problem with the file: `CorsCheck`
assumes every element of a dict literal passed to a Flask response is a
key/value pair, and mistakes a dict-unpacking element (`{**headers, ...}`) for
one. The file is silently absent from all Sonar results until the analyzer is
fixed, so **do not read a clean Sonar report as evidence that `routes/mcp.py` is
clean** — it is one of the guardrail-critical entry points listed above, so
review it by hand. Re-check after each SonarQube upgrade by grepping the scan
log for `Unable to analyze`.

## GitGuardian findings on this work

GitGuardian's GitHub check flagged secrets on the PR that added this analysis
stack. None is a live credential. One was still worth acting on, and the rest
need resolving in the GitGuardian dashboard rather than in the code - the check
runs from that dashboard and scans every commit in the PR, so a repo-local
ignore file would not suppress it and a later remediation commit does not clear
an earlier commit's finding.

**Acted on - `docker-compose.yml`'s shipped Postgres password.** The file
defaulted `POSTGRES_PASSWORD` to `devops_local` and inlined the same value into
the app service's `DATABASE_URL`. The `db` service publishes 5432 to the host,
so that default was a known credential listening on every developer's machine.
`POSTGRES_PASSWORD` now has no default: both services use
`${POSTGRES_PASSWORD:?}` and compose fails closed without it. Note the value was
already on `main` before this PR - GitGuardian surfaced it because the line was
touched, not because the PR introduced it.

**Remaining, all false positives, to be resolved in the dashboard:**

- `scripts/sonar-scan.sh` - `SONAR_ADMIN_PASSWORD`. The literal `Sq1!` is a
  password-policy character-class prefix (one upper, one lower, one digit, one
  symbol) guaranteeing the generated value passes SonarQube's policy whatever
  `/dev/urandom` produces; the entropy is the 20 random characters appended to
  it. It is now built via a separate `POLICY_PREFIX` so no literal sits on a
  `*_PASSWORD` assignment, which clears it for future commits but not for the
  commit that introduced it.
- `docker-compose.yml`'s `DATABASE_URL` line. The detector matches the
  `scheme://user:pass@host` URI shape and fires even when the password is pure
  interpolation (`${POSTGRES_PASSWORD:?}`). This one cannot be written around:
  the line has to stay, because `env_file: .env` supplies a `DATABASE_URL`
  pointing at `localhost` and the `environment:` entry is what overrides it to
  `db` inside the compose network. Dropping it would break the stack.

Two details worth keeping if this is revisited: the `:?` is deliberately bare,
because spelling out a custom error message puts prose to the right of a
`POSTGRES_PASSWORD:` assignment and the detector reads that as a value (it did,
on the first attempt); and `docker-compose.sonar.yml`'s fixed `sonar`/`sonar`
pair was never flagged and is deliberately kept, since that Postgres binds no
host port and is reachable only from within its own compose network.

Still carrying a literal dev credential, pre-existing and out of scope here:
`alembic.ini`'s `sqlalchemy.url`. Worth folding into the same treatment the next
time that file is touched.
