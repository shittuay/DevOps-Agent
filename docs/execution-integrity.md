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

## Phase 3 — shipped (rule 5: credit protection)

Branch `feat/credit-protection`. Two pieces, both lightweight — the per-turn
credit model is unchanged (1 credit per completed turn, deduction gated on
`success`; "failed calls don't consume credits" is already true at that
level).

### Low-credit warning

`app._low_credit_warning(credits_remaining)` returns a
`{'credits_remaining', 'message'}` payload when the post-turn balance is
`1..LOW_CREDIT_THRESHOLD` (5) — attached to the `/api/chat` JSON response as
`low_credit_warning` and to the `/api/chat/stream` `done` SSE event. `0` and
below is left to the existing exhausted-trial upgrade pitch. `templates/index.html`
shows it as a toast via `maybeWarnLowCredit()`, deduped on the balance value
so a user at 3 credits isn't toasted every message. (The one-time email at
exactly 5 is unchanged; this is the every-turn UI signal.)

### 60s read-result cache — `services/tool_cache.py`

`READ_CACHE` (`_ReadCache`, process-wide, thread-safe) caches **successful**
**read** tool results by `(user_id, tool_name, canonical_args)` for
`TTL_SECONDS = 60`, bounded at 512 entries (oldest-expiry evicted).

- **Read** = name starts `get_` / `list_` / `describe_`, contains `_api_read`,
  or is `find_ami` / `search_tools` — minus a deny-list of live/secret/volatile
  reads (`get_secret_value`, `generate_s3_presigned_url`,
  `get_ec2_console_output`, …).
- `DevOpsAgent._invoke_tool(name, input)` replaces the bare
  `self.tools[name](**input)` at all 5 execution sites: cache-lookup for reads,
  store on a successful read, and **`READ_CACHE.invalidate_user(uid)` after any
  mutating call** — a stale read that contradicts a just-applied change is
  exactly what the Phase 2 verifier exists to prevent, so mutations blow the
  whole user's read cache (coarse on purpose: mutations are rare).
- `canonical_args` = `DevOpsAgent._repeat_key` (same normalisation the repeat
  guard uses).
- Kill-switch `tool_cache.enabled` (default `true`). Disabled in tests whose
  `config.get` returns `None`.
- The Phase 2 verifier's own read-backs call `self.tools.get(name)` directly,
  not `_invoke_tool` — deliberately un-cached so verification is always fresh.

Tests: `tests/test_tool_cache.py`.

## Not-covered

- Rule 5's literal "warn *before* the operation" (a confirm-to-proceed gate)
  — a chat turn's message is already sent by the time the server sees the
  balance; the every-turn `low_credit_warning` informs the *next* message
  instead.

## Phase 4 — shipped (rule 4: IaC fallback generation)

Branch `feat/iac-fallback`. `services/iac_fallback.py` +
`DevOpsAgent._iac_fallback`.

- When a **creating** tool returns `{'success': False}`,
  `generate_cloudformation(tool_name, tool_input)` builds a compact
  CloudFormation template (JSON) from the *same intent* and
  `_verify_and_annotate` attaches it as `_iac_fallback` on the failed result:
  `{'format': 'cloudformation', 'stack_name', 'template', 'resource_type',
  'apply'}`. `apply` spells out the `create_cloudformation_stack(...)` call.
- `_iac_fallback` also **appends `create_cloudformation_stack` to
  `_tools_override`** so the model can run it this turn even if progressive
  loading never offered it.
- The `STABLE_SYSTEM_PROMPT` **IaC FALLBACK PROVIDED** line tells the model to
  quote the real error, say a template is ready, and call
  `create_cloudformation_stack` with the `template` string as `template_body`
  — never paste the whole template at the user or send them to the console.
- **Supported set:** `create_ec2_instance` / `run_instances` →
  `AWS::EC2::Instance` (needs a concrete `ami_id`, else `None`);
  `create_security_group` → `AWS::EC2::SecurityGroup` (maps `ingress_rules`);
  `create_vpc` → `AWS::EC2::VPC`; `create_s3_bucket` → `AWS::S3::Bucket`
  (versioning / SSE-S3 / public-access-block).
- **`create_rds_instance` is omitted** — its `MasterUserPassword` would have to
  be embedded in the template or threaded through a `NoEcho` parameter;
  deferred rather than risk a plaintext secret in the template artifact.
- **Guards:** one `_iac_fallback` per turn (`_iac_fallback_emitted`); skipped
  in sandbox; kill-switch `iac_fallback.enabled`; any exception leaves the
  result untouched. `iac_fallback.py` is pure — it never applies a template.

Tests: `tests/test_iac_fallback.py`.

## Not covered

- **Terraform** generation (CloudFormation only for now).
- **`retry_queue`** — deferred execution of a failed op via a DB table +
  worker. Separate subsystem; the synchronous IaC fallback covers the common
  "the create failed, do it another way now" case.
- RDS / IAM / networking-graph (VPC + subnets + route tables) templates.

## Deferred — decisions recorded

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
