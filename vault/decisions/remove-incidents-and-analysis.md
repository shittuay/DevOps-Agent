---
date: 2026-10-13
type: decision
tags: [product, cleanup, incidents]
---

# Remove Incidents and Analysis

**Decision:** Delete the Incidents pages and engine (`/incidents`, playbooks, correlation groups, investigation journal) and the Analysis (root-cause) pages, at the owner's request.

**Why:**
- With [[remove-monitoring-engine]] done, nothing was creating incidents except CI/CD webhook failures and a developer API endpoint that had been broken all along (it imported a model that doesn't exist). The pages would have stayed empty.
- Analysis only worked on incidents.
- Several attached surfaces kept needing security fixes, and one was still leaking: the public `/status` page listed every user's incidents.

**What stays:** incident handling moves to where customers already run it. The agent's PagerDuty and OpsGenie tools, the "Incident Response" chat workflows, and the incident-runbooks skill are unchanged.

**Left behind on purpose:** the `incidents`, `playbooks` and `incident_correlation_groups` tables and the `notify_incidents` column, so there is no destructive migration.

Related: [[remove-optimize-area]], [[remove-monitoring-engine]], all removed the same day.
