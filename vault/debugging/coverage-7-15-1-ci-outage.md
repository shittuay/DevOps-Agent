---
date: 2026-07-15
type: postmortem
tags: [ci, dependencies, coverage]
---

# coverage 7.15.1 took CI down for 5 days (Jul 13–15, 2026)

**What happened:** A `coverage` entry with a loose `>=` floor let the broken 7.15.1 release into CI, where it crashed the HTML coverage report on Jinja-traced templates. CI was red ~5 days; merges and auto-deploys were blocked.

**Fix:** `ci.yml`'s test job installs `'coverage>=7.15.2'` explicitly, and the whole of `requirements.txt` was converted to exact `==` pins ([[pin-requirements-exactly]], PR #50).

**Lesson:** Any dependency installed fresh on every CI run or deploy is effectively deployed unreviewed unless its version is exact. Watch for the same pattern in tool-versions inside GitHub Actions steps, not just requirements.txt.
