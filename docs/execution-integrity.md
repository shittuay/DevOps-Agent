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
| 1, 2, 3, 4, 7 | `=== EXECUTION INTEGRITY ===` block in `STABLE_SYSTEM_PROMPT` (`src/agent/core.py`). Prompt-cache invariants unchanged. |
| 8 | Dispatch is a dict lookup and cannot misroute — the model picks the wrong *name*. `_repeat_guard` (#171) + `tool-not-offered` log/DB signal (#173) already cover detection. Phase 1 adds **`_note_guard` / `_guard_notes_suffix()`**: a repeat-guard block, or the same tool guessed-and-not-offered ≥3×, appends a plain-language "Tool-selection note" to the user-facing response (all non-streaming + Kimi-streaming + Claude-streaming `end_turn` paths). Never replaces the response. |
| 9 | **Session resource registry.** `_is_creating_tool` + `_extract_created_resource_ids` (`core.py`) pull ids from a successful creating-tool result into `agent._created_resources` (per turn) and — via `_audit_infrastructure_change` (renamed from `_audit_chat_deletion`, `action_type='create'` branch added) — into `InfrastructureChange` rows carrying `change_details['conversation_id']`. `_session_resource_context()` reads them back (same conversation, last 30 min) into the volatile prompt tail through `build_volatile_tail(..., session_context=)`. |

Tests: `tests/test_execution_integrity.py`.

## Deferred — decisions recorded

### Rule 2 — verification engine (not started)

- **Synchronous, inside the turn**, backoff `1 → 2 → 5 → 7s`, **capped at
  ~15s** (not the spec's 60s — keeps turns responsive; the keepalive already
  holds the connection). On timeout, emit verbatim:
  *"Create returned ID `<X>`, but I cannot confirm it via a read yet — it may
  still be propagating. Please check the console."*
- New `services/mutation_verifier.py`: a map `mutating_tool -> (read_back_tool,
  resource_match_predicate)`. Called from the tool-execution paths in
  `core.py` right after a creating/mutating tool returns success, using the
  per-user credential path (never ambient creds — see the "every feature runs
  against a real cloud account" rule in CLAUDE.md).
- Feeds the same `_created_resources` registry, tagging each entry
  `verified: true|false`.

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
