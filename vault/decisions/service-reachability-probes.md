---
date: 2026-09-09
type: decision
tags: [tools, execution-integrity, verification, ssrf]
---

# The agent gets first-class reachability probes, and must report a 404 as a 404

**Decision:** New `src/tools/verification_tools.py` — `http_check` and
`tcp_check`, both read-only, SSRF-guarded, registered unconditionally and in
`ALWAYS_TOOL_NAMES`. Four new bullets in the `=== EXECUTION INTEGRITY ===` prompt
block: use the probe tools (never infer HTTP reachability from another tool's
error text); a non-2xx/3xx response means "port open, app not serving what you
intended" — say exactly that; name your blind spots when you can't see inside the
host; bake configuration into `user_data` on the first `create_ec2_instance` call
rather than launching bare and recreating.

**Why:** A production run ("launch a t3.micro, install nginx, verify port 80")
exposed three things. (1) `run_smoke_test` existed but is categorised `cicd`
(keywords jenkins/pipeline/build job), so progressive tool loading never offered
it for an EC2 task — the agent ran `git clone http://<ip>/` and reasoned from
`fatal: repository not found`. (2) That was an HTTP **404**; the agent reported
"nginx is running and serving … you'll see the custom page" — [[execution-integrity]]
rule 1 (verified results only) has no coverage for the service-serving case.
(3) The agent launched a bare instance, hit `ssm:SendCommand` /
`AssociateIamInstanceProfile` `AccessDenied`, terminated it (user confirmed), and
relaunched with `user_data` — a wasted create/terminate cycle.

**Consequences:**
- `http_check`/`tcp_check` are in `tool_cache._READ_DENY` — a probe must run live
  every call; a cached "reachable: false" from 60s ago would misreport a service
  that has since come up.
- `run_smoke_test` re-homed to a new `verification` selection category via a
  `classify_tool` name override — it stays in `cicd_tools.py` (sibling
  `auto_rollback_deployment`, wired into the CLAUDE.md SSRF list).
- New `assert_safe_host()` in `network_safety.py` for the raw-socket path
  (`tcp_check`) — same policy as `assert_safe_url`, no scheme.
- The `capability` blocks on the two tools are forward-compatible with the
  Phase-1 governance refactor ([[tool-capability-metadata]], PR #181, still open)
  and inert until it lands.
- Out of scope: mapping SSM/console `AccessDenied` to the published IAM policy,
  widening `static/iam/devops-agent-management.json`, provisioning an SSM
  instance profile, `iam_instance_profile` on `create_ec2_instance`.

Full plan: the harness-comparison follow-up plan (2026-09-09). Doc:
`docs/execution-integrity.md` Phase 6.
