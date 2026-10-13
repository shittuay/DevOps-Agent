---
date: 2026-10-13
type: decision
tags: [product, fabricated-data, cleanup]
---

# Remove the Optimize area instead of rebuilding it

**Decision:** Delete `/optimization` (route, templates, `services/performance_optimizer.py`, `services/prevention_engine.py`) rather than wire it up to real data.

**Why:**
- It first shipped fabricated recommendations (`i-0abc123def456`) to every user. The 2026-09-20 audit stripped those out, but nothing ever fed `analyze_resource()` live data, so the page rendered an empty list.
- Everything real it could have shown already exists elsewhere. `services/cost_explorer.py` backs the dashboard's costs and the `get_optimization_recommendations` agent tool. A second, empty view only cost maintenance and a nav slot.

**Consequences:**
- The `ProactiveRecommendation` table stays in the database, unused.
- Notifications that linked to `/optimization` now go to `/dashboard`.
- `tests/test_optimize_removed.py` fails the build if a link or `url_for('optimization.…')` comes back.
