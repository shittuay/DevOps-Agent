# Execution Integrity & Resilience

The agent's value proposition is "I do it for you." Every time it says "go do
it yourself", fabricates a result, or narrates a fake platform fault, that
promise breaks. This document is the spec for keeping it intact, plus the
record of what is shipped vs. deferred.

Origin: a live incident (2026-09-02) where "create an EC2 instance" ran
`nmap_port_scan` x150 and `create_ec2_instance` zero times, narrated to the
user as "misrouted". Direct fixes landed in PRs #171 (`_repeat_guard`
loop-breaker, progressive-loading repair) and #173 (`_record_tool_call` /
`tool-not-offered` observability). This spec hardens against the whole class.

## The 9 rules

1. **Verified results only** — never report a create/update/delete as done
   until a read confirms it; every ID/IP/ARN/state shown is verbatim from a
   tool result.
2. **Eventual-consistency handling** — verify mutations with backoff; never
   say "does not exist" for a resource created in the last 5 minutes.
3. **Error honesty** — quote tool errors verbatim (code first); classify every
   non-success as (a) tool error / (b) empty / (c) success-but-unverified;
   never invent a subsystem fault.
4. **Mandatory fallback chain** — retry → generic `*_api_*` → generate
   IaC/CLI the platform can run → queue. Never send the user to the console
   as a first response.
5. **Credit protection** — warn under 5 credits; cache reads 60s; failed tool
   calls must not consume credits.
6. **Graceful plan degradation** — offer the nearest eligible alternative
   instead of hard-failing.
7. **User override on state disputes** — console evidence beats agent
   inference; trust the user, re-verify, correct the record.
8. **Routing integrity** — log `tool_requested` vs `tool_executed`; surface a
   misrouting/retry storm to the user, don't loop silently.
9. **Session resource registry** — track resources created this session;
   cross-check before reporting any as absent.

## Phase 1 — shipped

Prompt rules + cheap guardrail hooks. Branch `fix/execution-integrity-phase1`.

| Rule | What shipped |
|---|---|
| 1, 2, 3, 4, 7 | `=== EXECUTION INTEGRITY ===` block in `STABLE_SYSTEM_PROMPT` (`src/agent/core.py`). Prompt-cache invariants unchanged. Rule 2's *runtime* read-back is Phase 2 below. |
| 8 | Dispatch is a dict lookup and cannot misroute — the model picks the wrong *name*. `_repeat_guard` (#171) + `tool-not-offered` log/DB signal (#173) already cover detection. Phase 1 adds **`_note_guard` / `_guard_notes_suffix()`**: a repeat-guard block, or the same tool guessed-and-not-offered ≥3×, appends a plain-language "Tool-selection note" to the user-facing response (all non-streaming + Kimi-streaming + Claude-streaming `end_turn` paths). Never replaces the response. |
| 9 | **Session resource registry.** `_is_creating_tool` + `_extract_created_resource_ids` (`core.py`) pull ids from a successful creating-tool result into `agent._created_resources` (per turn) and — via `_audit_infrastructure_change` (renamed from `_audit_chat_deletion`, `action_type='create'` branch added) — into `InfrastructureChange` rows carrying `change_details['conversation_id']`. `_session_resource_context()` reads them back (same conversation, last 30 min) into the volatile prompt tail through `build_volatile_tail(..., session_context=)`. |

Tests: `tests/test_execution_integrity.py`.

## Phase 2 — shipped (rule 2)

`services/mutation_verifier.py` + `DevOpsAgent._verify_and_annotate`. Branch
`feat/mutation-verifier`.

- After a **creating** tool returns `success: True`, the resource's dedicated
  read tool is called with a short backoff — `DEFAULT_BACKOFF = (0, 1, 2, 5, 7)`
  seconds, ~15s wall time, 5 attempts (first immediate). Not the spec's 60s:
  the keep-alive holds the connection but every extra second is a slower
  reply.
- A `_verification` key is added to the tool result the model reads next
  iteration: `{'status': 'confirmed', 'resource_id', 'via', 'after_seconds'}`
  or `{'status': 'unconfirmed', 'resource_id', 'via', 'message'}` where
  `message` is the verbatim *"Create returned ID `<X>`, but I cannot confirm
  it via a read yet…"*. The system prompt's AUTOMATIC VERIFICATION line tells
  the model `unconfirmed` ≠ failed.
- The read runs through `self.tools[read_tool]`, i.e. the same per-user cloud
  client the create used — never ambient creds.
- The `_created_resources` registry entry for the id is tagged
  `verified: true|false`.
- **Verifiable tools** (Phase 2 set): `create_ec2_instance` / `run_instances`
  → `get_ec2_instances`; `create_security_group` → `describe_security_group`;
  `create_vpc` → `describe_vpc`; `create_rds_instance` →
  `describe_rds_instance`; `create_s3_bucket` → `get_s3_bucket_info`. Each
  read echoes the queried id on success, so confirmation = `success is True`
  **and** the id appears verbatim in the read payload.
- **Guards:** skipped in sandbox mode; kill-switch `mutation_verify.enabled`
  (default `true`); capped at `MAX_VERIFICATIONS_PER_TURN = 3` per turn (a
  turn launching 10 instances must not add 150s — the rest are registered
  unverified); any exception leaves the result untouched.
- **Not covered:** updates (`Phase 2c`, not started).

Tests: `tests/test_mutation_verifier.py`.

## Phase 2b — shipped (delete verification)

Same module, `_DELETE_SPECS` + `verify_mutation`'s `action='delete'` branch,
same wiring (`_verify_and_annotate` at the 5 execution sites — a delete result
is `{'success': True}` and flows through identically).

- After a **deleting** tool succeeds, the read-back per attempt resolves to
  `gone` / `present` / `unknown`:
  - **`gone`** → `_verification.status = 'confirmed'`. A describe-by-id read
    that 404s with a code in `_NOT_FOUND_CODES` (`InvalidGroup.NotFound`,
    `InvalidVpcID.NotFound`, `DBInstanceNotFound`, …); an EC2 instance in
    `shutting-down`/`terminated` (`_EC2_TERMINAL_STATES`) or absent from the
    filtered list; an S3 bucket absent from `list_s3_buckets`.
  - **`present`** → after all attempts, `unconfirmed` with *"Delete of `<X>`
    returned success, but a read still shows it — it may still be shutting
    down…"*.
  - **`unknown`** → a read that failed for a **non**-NotFound reason
    (`AccessDenied`, `Throttling`) is **never** read as `gone` — that is the
    "cannot read the account vs. a finding" trap. After all attempts,
    `unconfirmed` with *"`<X>` was deleted … but I could not verify removal —
    the read-back is failing…"*.
- **Delete-verifiable set:** `delete_ec2_instance` /
  `manage_ec2_instance(action='terminate')` → `get_ec2_instances`;
  `delete_security_group` → `describe_security_group`; `delete_vpc` →
  `describe_vpc`; `delete_rds_instance` → `describe_rds_instance`;
  `delete_s3_bucket` → `list_s3_buckets` (not `get_s3_bucket_info` — that one
  swallows `NoSuchBucket` and returns `success: True`).
- `manage_ec2_instance` only verifies when `action == 'terminate'`
  (`_DeleteSpec.applies` + `will_verify()` so a non-terminate action spends no
  per-turn slot).
- The `_created_resources` registry is tagged only for `action == 'create'` —
  a create-then-delete in one turn must not flip a deleted resource to
  `verified: true`.

## Phase 2c — shipped (update verification)

Same module, `_UPDATE_SPECS` + `verify_mutation`'s `action='update'` branch.
`verify_mutation` was refactored into `_pick_spec` (dispatch, honours each
spec's `applies`) + a shared `_poll` loop + three per-action tails.

- After an **updating** tool succeeds, the read-back per attempt resolves to
  `applied` / `not_yet` / `unknown` via `_update_state`: build the
  `{read_field: target}` map from the params the caller actually passed
  (`_UpdateSpec.expected`), find the resource in the read (`find`, for
  list-style reads), and compare.
  - **`applied`** → `_verification.status='confirmed'`, plus a `fields` list.
    An `accepted_states` hit (RDS `status == 'modifying'`) also counts as
    applied — the change was accepted and is in flight.
  - **`not_yet`** → after all attempts, `unconfirmed` — "a read does not yet
    show the new value for `<fields>`, may still be applying".
  - **`unknown`** → the read failed, or nothing checkable was passed. After
    all attempts, `unconfirmed` — "could not verify the new value".
- **Update-verifiable set:** `resize_ec2_instance` → `get_ec2_instances`
  (`instance_type`); `manage_ec2_instance(action in start/stop/reboot)` →
  `get_ec2_instances` (`state`); `update_ecs_service` → `list_ecs_services`
  (`desired_count`); `update_lambda_function_config` → `list_lambda_functions`
  (`memory_size`/`timeout`/`runtime`); `modify_rds_instance` →
  `describe_rds_instance` (`db_instance_class`/`engine_version`, or
  `status == 'modifying'`).
- `manage_ec2_instance` is now in all three spec maps: `terminate` → delete,
  `start`/`stop`/`reboot` → update, anything else (`describe`) → not verified.

## Not covered

Security-group rule changes (`authorize_*`/`revoke_*` — the "expected" is a
rule shape, not a scalar), tag operations, and IaC-shaped updates
(`update_cloudformation_stack`). Add a `_UpdateSpec` per tool as the need
arises.

## Deferred — decisions recorded

### Rule 5 — credit protection (not started)

- **Pre-flight warning** when `CreditService.balance(user) < 5`, added to the
  chat routes (`app.py` `/api/chat`, `/api/chat/stream`) before the agent
  call — today the only signal is a one-time email at exactly 5, sent *after*
  the turn.
- **60s read-result cache** keyed by `(user_id, tool_name, canonical_args)`,
  wrapping read-only tool dispatch in `core.py`. Canonical args = the same
  `_repeat_key` normalisation.
- **Leave the per-turn credit model as-is** — 1 credit per completed turn, no
  per-tool accounting. "Failed calls don't consume credits" is already true
  at the turn level (deduction is gated on `success`). Full per-tool
  accounting was explicitly rejected as too invasive for the billing tests
  and the conversion funnel.

### Rule 4 — runtime fallback (not started)

- Real CloudFormation/Terraform **generation** from a failed tool call's
  intent, and a `retry_queue` table for deferred execution, are net-new
  subsystems. The prompt already instructs the ordering; the runtime
  automation is a separate project.

### Rule 6 — dropped

No feature gates cloud instance types (or any resource shape) by subscription
tier. Tiers gate the AI model, credits, rate limits, and `max_tools` — not
what the user can launch. The "offer the nearest alternative, don't
hard-fail" intent is covered by rule 4's prompt guidance and AWS's own
capacity/quota errors surfacing through rule 3.

### Rule 8 — `/v1/agent` developer API

`routes/api_gateway.py` has its own tool-execution + usage-log write path
(`action_type='api_tool_use'`) with the same turn-vs-tool `success`
conflation PR #173 fixed for the chat paths. Not touched here; flagged.
