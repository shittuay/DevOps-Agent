---
id: incident-runbooks
name: Incident Response Runbooks
triggers: [incident, outage, down, degraded, alert, pagerduty, on-call, sev1, sev2, p1, p2, runbook, response, investigate, root cause, postmortem, rca, mitigation]
compatible_providers: [aws, azure, gcp, kubernetes]
---
# Incident Response Runbook Templates

## Incident Severity Definitions
| Level | Criteria | Response Time |
|---|---|---|
| SEV1/P1 | Production down, all users affected | Immediate (< 5 min) |
| SEV2/P2 | Major degradation, >50% users affected | < 15 min |
| SEV3/P3 | Partial degradation, workaround exists | < 1 hour |
| SEV4/P4 | Minor issue, no user impact | < 24 hours |

## Standard Response Steps
1. **Acknowledge** — assign owner, update status page, start war room
2. **Triage** — confirm scope (what's broken, who's affected, since when)
3. **Mitigate** — restore service using rollback, failover, or scaling before investigating root cause
4. **Investigate** — use monitoring, logs, traces to find root cause
5. **Resolve** — apply permanent fix; verify in production
6. **Document** — write postmortem within 48 hours

## Common Mitigations
- **Traffic spike → 503**: Scale up replicas (`update_deployment` with increased `replicas`)
- **Bad deploy**: Roll back deployment (`describe_deployment`, then `update_deployment_image` with previous tag)
- **Database overload**: Enable RDS read replicas; route read traffic away
- **Memory leak**: Restart pods with rolling restart; add memory alert for early warning next time
- **Upstream dependency down**: Activate circuit breaker; return cached responses

## Investigation Workflow
1. When did the issue start? (check deploy history, config changes)
2. What changed? (deploys, config pushes, infrastructure changes in last 2 hours)
3. What does monitoring show? (CPU, memory, error rate, latency — correlate with incident start)
4. Are there error patterns in logs? (5xx spike, exception type, correlation IDs)
5. Is it isolated or cascading? (check service map / distributed traces)

## DevOps Agent Commands
- `list_incidents` to see current active incidents
- `get_pod_logs` for Kubernetes service investigation
- `get_aws_cloudwatch_logs` for application logs
- `get_infrastructure_summary` for resource state overview
