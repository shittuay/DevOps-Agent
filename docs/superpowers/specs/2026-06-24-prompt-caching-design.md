# Phase 2 — Anthropic Prompt Caching (Design Spec)

> Status: approved design, pending implementation plan.
> Date: 2026-06-24. Branch: `feat/harness-phase1-context-and-tool-loading` (Phase 2 builds on Phase 1).
> Scope: **B** (system+tools prefix **and** conversation prefix), lean — see "Accepted limits".

## Problem

Every Claude API call in the agent re-sends a large static system prompt (~160 lines, `core.py:843–1008`, comfortably >2048 tokens) plus the full tool schema set, on **every iteration** of the tool-use loop (up to 50 iterations per user message). That fixed prefix is paid at full input price each time. Anthropic prompt caching can serve a repeated prefix at ~0.1× cost after a one-time write.

This applies to the **Claude path only** (professional/business tiers → `claude-sonnet-4-6`; starter → `claude-haiku-4-5`, all via `model_override`). Kimi (free/starter default, OpenAI-compatible) uses a different mechanism and is **out of scope**.

## Goal

Cache the stable prefix so the second-through-Nth iterations of a tool loop (and, best-effort, subsequent turns within the 5-minute TTL) read it from cache instead of reprocessing it. Primary, dependable win is **breakpoint 1 (tools + system)**; breakpoint 2 (conversation prefix) is best-effort.

## Caching mechanics (ground truth)

- Prefix match. Render order `tools → system → messages`. Any byte change in the prefix invalidates everything after it.
- `cache_control: {type: "ephemeral"}` (5-min TTL) on a content block. **Max 4 breakpoints/request.** A breakpoint on the last `system` block caches tools+system together (tools render first).
- Minimum cacheable prefix: Sonnet 4.6 = 2048 tokens, Opus 4.x = 4096. Below minimum → silently no cache, no error.
- Invalidation hierarchy: changing **tool definitions** invalidates tools+system+messages (everything); changing **system** invalidates system+messages but not tools.
- 20-block lookback: a message breakpoint walks back ≤20 content blocks to find a prior entry.
- Verify hits via `response.usage.cache_read_input_tokens` / `cache_creation_input_tokens`.

## Design

### New module: `src/agent/prompt_cache.py`

Pure functions, no I/O, fully unit-testable.

```python
def build_cached_system(stable_core: str, volatile_tail: str | None) -> list[dict]:
    """Breakpoint 1. Returns Anthropic `system` as content blocks:
       [{type:text, text:stable_core, cache_control:{type:ephemeral}}, {type:text, text:volatile_tail}]
       The second block is omitted when volatile_tail is empty/None."""

def apply_message_breakpoint(messages: list[dict]) -> list[dict]:
    """Breakpoint 2. Returns a messages list where the LAST message is DEEP-COPIED
       and its last content block carries cache_control:{type:ephemeral}.
       - Normalizes a string `content` into a one-block list first.
       - No-op (returns input) on an empty list.
       - MUST NOT mutate the input/stored messages (see 'Deep-copy is load-bearing')."""
```

### System-prompt split: `_build_system_prompt_parts()`

Refactor `_build_system_prompt` (`core.py:832`) so assembly produces two pieces:

- `stable_core` — the fully static text currently at lines 843–1008. Verified byte-stable: no datetime/uuid/per-user/counter interpolation anywhere before the tail.
- `volatile_tail` — `"User Preferences and Context:\n" + preferences + (trial_context)`.

**Implementation note (review finding #4):** the `User Preferences and Context:` header currently lives at the *end of the same string literal* (lines 1009–1010). The refactor must physically relocate that header line into `volatile_tail`, not leave it dangling at the end of `stable_core`. When `preferences` is empty, `volatile_tail` should be `"User Preferences and Context:\nNo specific preferences set."` (matching today's behavior), never a bare dangling label.

- Keep `_build_system_prompt()` returning the **joined string** (unchanged) — the two Kimi callers (`_call_kimi_api` ~1201, `_call_kimi_api_streaming` ~1404) keep using it.
- Add `_build_system_prompt_parts(...) -> tuple[str, str | None]` for the two Claude callers.

### Wiring (the two — and only two — Anthropic call sites)

Verified by grep `self.client.messages`: exactly two sites.
- `_call_claude_api` non-streaming, `core.py:1056` (`self.client.messages.stream(**api_params).get_final_message()`)
- streaming path in `process_message_streaming`, `core.py:780` (`self.client.messages.stream(**api_params)`)

At each site:
```python
if self.config.get('prompt_cache.enabled', True):
    core, tail = self._build_system_prompt_parts(user_preferences_context, trial_context=trial_context)
    api_params['system']   = build_cached_system(core, tail)        # bp1
    api_params['messages'] = apply_message_breakpoint(api_params['messages'])  # bp2
else:
    api_params['system'] = self._build_system_prompt(...)           # legacy plain string
```
Exactly **2 of 4** breakpoints used. The SDK accepts a block-list `system` (confirmed).

**Model-scoping (review finding #5):** caches are model-scoped. The cached path must use the same resolved model that's actually sent — `model_override` (`core.py:768/1044`), which resolves to `claude-sonnet-4-6` — never fall through to the stale dated default `self.config.claude_model` (`claude-sonnet-4-20250514`, `config_manager.py:259`). No code change needed beyond *not* introducing a model fallback in the cached path; documented so the plan doesn't regress it.

### Config

`prompt_cache.enabled` (default `true`), read via `self.config.get('prompt_cache.enabled', True)` — mirrors Phase 1's `tool_selection.enabled` (`core.py:492`).

### Observability

After each Claude call, log at INFO: `cache_read_input_tokens` and `cache_creation_input_tokens` from `response.usage` (both paths expose `usage`; streaming via `stream.get_final_message().usage`). This is the success signal — **bp1 cache_read > 0 across loop iterations is the SLA.**

## Deep-copy is load-bearing (review finding #3)

`Message.to_dict()` (`conversation.py:48–51`) returns `{'role', 'content': self.content}` — it **shares the stored `content` list reference**; `get_messages_for_api()` (`conversation.py:133`) does not copy. If `apply_message_breakpoint` tagged blocks in place, `cache_control` would be written into persisted history and **accumulate every loop iteration**, exceeding 4 breakpoints → 400. The deep-copy of the last message (and its last block) is therefore a correctness requirement, guarded by a dedicated test.

## Accepted limits (documented, not fixed in Phase 2)

Per decision: keep B lean; bp1 is the durable win, bp2 is best-effort.

1. **Compaction defeats bp2 mid-turn (review finding #1).** Phase 1's `_compact_old_tool_results` (`conversation.py:208–244`) rewrites old `tool_result` bytes in place on every append (via `_trim_history`). Rewriting bytes at position N invalidates the message cache from N onward, so bp2 loses value in long, tool-heavy turns. **bp1 (tools+system) is positional at the front and unaffected.** No change to Phase 1 compaction.
2. **`search_tools` invalidates the entire cache within a turn (review finding #2).** The Phase 1 meta-tool (`core.py:524–528`) mutates `self._tools_override` mid-loop; a tool-definition change wipes tools+system+messages on the next iteration. Expected to fire rarely; documented, not prevented.
3. **20-block lookback (review finding #7).** Long agentic turns add >20 message blocks, so bp2's incremental reads can miss. Compounds with limit #1. bp1 still hits.
4. **bp2 token minimum (review finding #6).** A single `tool_result` message is often <2048 tokens (Sonnet minimum), so bp2 silently won't cache on short turns — no error, no benefit. Success is measured on bp1.

## Out of scope / latent issues to flag (not fix)

- **`temperature` on Opus (review finding #5).** `claude_temperature` (default 0.7, `config_manager.py:269`) is sent on both Claude sites (`core.py:770/1046`). Sonnet 4.6 / Haiku 4.5 accept it — no 400 today. But CLAUDE.md/model-tier docs describe "business = Opus"; if biz is ever pointed at a real Opus 4.7/4.8, this line will 400. Flagged for the maintainers; not changed here.
- **Scope C** (sticky/union tool selection per conversation so cross-turn caching survives Phase 1 reselection) — deferred to a future phase.

## Testing — `tests/test_prompt_cache.py`

- `build_cached_system`: stable core block carries `cache_control`, volatile tail block does not; order preserved; tail omitted when empty.
- `apply_message_breakpoint`: last block of last message tagged; string `content` normalized to a one-block list; empty list → no-op; single-message case.
- **Stored history is NOT mutated** — call `apply_message_breakpoint` on the output of `get_messages_for_api()` and assert the underlying `ConversationManager.messages` gains no `cache_control` (the load-bearing test).
- `prompt_cache.enabled=false` → plain-string passthrough at both call sites.
- Determinism: identical inputs → byte-identical `stable_core` (guards against a future silent invalidator).

## Success criteria

- `prompt_cache.enabled=true`: across iterations of a multi-tool turn on a Claude model, `cache_read_input_tokens` > 0 from the 2nd iteration onward (bp1 hit).
- `prompt_cache.enabled=false`: behavior byte-identical to today (string `system`, no `cache_control`).
- Full suite green; Kimi paths unchanged.
