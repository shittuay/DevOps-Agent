---
date: 2026-07-15
type: decision
tags: [dependencies, ci, deploy]
---

# Pin requirements.txt exactly (==, never >=)

**Decision:** `requirements.txt` is fully `==`-pinned as of 2026-07-15 (PR #50). Upgrades happen by changing the pin in a PR so CI tests the exact version before it can reach production.

**Why:** The EC2 deploy runs `pip install -r requirements.txt` on every push to main. A loose floor (`>=`) means whatever version PyPI serves at deploy time reaches production unreviewed. This is exactly how the [[coverage-7-15-1-ci-outage]] happened.

**Consequences:**
- Security floors from `pip-audit` become exact pins at (or above) the fixed version, with the advisory ID in a trailing comment.
- Never "fix" a CVE by loosening to `>=` — bump the pin instead.
