# Session Handoff — Migration Testing

## Context

A full code review was run on branch `claude/gifted-hopper-ZYlny`. 14 bugs were
found and fixed across `scripts/migrate_sqlite_to_pg.py` and `app.py`. All
app.py fixes were verified with Playwright. The migration script fixes require a
live PostgreSQL database to validate — that's the remaining work.

## Branch

```bash
git fetch origin
git checkout claude/gifted-hopper-ZYlny
```

## What Was Fixed (already committed)

### scripts/migrate_sqlite_to_pg.py
1. `UserCloudCredential` was imported but never migrated — added full migration block
2. SQLite datetime strings crashed psycopg2 — added `_parse_dt()` helper
3. `credits_remaining or 20` reset 0-credit users to 20 — fixed to explicit `None` check
4. `email_verified` defaulted `True` for old-schema users — changed to `False`
5. `learning_level` string `'beginner'` written to JSON column — normalised to `{}` via `_parse_learning_level()`
6. Conversations had no dedup check — re-runs would duplicate all history
7. `fetchall()` on messages risked OOM — replaced with `fetchmany(500)` batch loop
8. `pg_tier_id` silently `None` if 'free' tier absent — added early exit guard
9. `sqlite.close()` not in `finally` — WAL lock held on exception
10. O(N²) `User.query.all()` inside user loop — moved to set built once before loop

### app.py
11. `_onboarding_ok` set rebuilt on every request — moved to module-level constant `_ONBOARDING_OK_ROUTES`
12. `request.endpoint` is `None` on 404 — added `and request.endpoint` guard so 404s stay 404
13. `learning_proficiency`, `learning_paths`, `learning_session_summary` — added `isinstance(dict)` guard to match models.py fix

### requirements.txt
14. `urllib3==2.6.3` — two CVEs (PYSEC-2026-141, PYSEC-2026-142) — bumped to `>=2.7.0`

## Your Task: Validate the Migration Script Against Real PostgreSQL

The app.py fixes are done. The migration script needs a live run.

### Step 1 — Copy your SQLite file
```bash
cp /path/to/your/devops_agent.db /tmp/devops_agent.db
# or set the path explicitly:
export SQLITE_PATH=/path/to/devops_agent.db
```

### Step 2 — Set your DATABASE_URL to PostgreSQL
```bash
export DATABASE_URL=postgresql://user:pass@localhost:5432/devops_agent
```

### Step 3 — First run
```bash
cd /path/to/DevOps-Agent
python3 scripts/migrate_sqlite_to_pg.py
```

Expected output:
- `PG tiers: {'free': 1, 'starter': 2, ...}` — tiers found, no early exit
- Users listed as `ADDED email@... -> PG id=N`
- `Cloud credentials migrated: N` — must be > 0 if users had credentials
- `Conversations: N migrated`, `Messages: N migrated`
- No `skipped:` lines (those indicate an exception)

### Step 4 — Verify in PostgreSQL
```sql
SELECT COUNT(*) FROM users;
SELECT COUNT(*) FROM user_cloud_credentials;   -- must not be 0
SELECT COUNT(*) FROM conversations;
SELECT COUNT(*) FROM chat_messages;
SELECT credits_remaining FROM user_subscriptions;  -- no unexpected 20s for 0-credit users
SELECT email_verified FROM users;                  -- should match source data
```

### Step 5 — Idempotency check (run twice, counts must not change)
```bash
python3 scripts/migrate_sqlite_to_pg.py
```
```sql
-- Row counts must be identical to Step 4
SELECT COUNT(*) FROM conversations;
SELECT COUNT(*) FROM chat_messages;
```

### Step 6 — Merge
Once migration validates:
```bash
# On GitHub: open a PR from claude/gifted-hopper-ZYlny -> main
# Merging clears the 2 Dependabot alerts on the default branch
```

## Known Non-Issues

- `config/.env` — ignored by git, contains only local test placeholders, never committed
- Stripe warnings at startup — expected with placeholder keys, does not affect migration
- Dependabot alerts on `main` — will clear after merge (urllib3 bump is on this branch)
