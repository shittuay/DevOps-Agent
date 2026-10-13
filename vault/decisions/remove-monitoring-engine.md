---
date: 2026-10-13
type: decision
tags: [product, cleanup, incidents]
---

# Remove Monitoring: the page and the alert→incident engine

**Decision:** Delete `/monitoring` together with `services/proactive_monitoring.py`, rather than only hiding the page. The agent's Prometheus/Datadog/Grafana tools stay.

**Why the engine went too:**
- Without the page, nobody could view or edit the alert rules. The engine would have kept seeding default rules and opening incidents from them every 60 seconds, with no way to see why or switch it off. That is worse than no automation.

**What changed for users:**
- Incidents are no longer auto-opened from metric alerts. Manual and webhook-created incidents, RCA, and incident notifications still work.
- ChatOps lost `/alerts` and `/metrics`; `/status` now shows incident stats only.
- Status-page subscribers no longer get alert broadcasts.

**Left behind on purpose:**
- The `MonitoringRuleModel` and `MonitoringAlertModel` tables, so there is no destructive migration.
- `status_service.broadcast_incident()`, which now has no caller.

Related: [[remove-optimize-area]], removed the same day.
