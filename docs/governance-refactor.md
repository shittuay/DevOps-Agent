# Governance Refactor

Porting the deterministic governance layer from `devops-agent-harness` into this
codebase, as seven sequenced phases. This document is the spec plus the record of
what is shipped vs. deferred. Full plan and rationale:
the harness architecture comparison (2026-09-06).

## The through-line

One structural defect shows up three times in `CLAUDE.md`, each costing recurring
scheduled-audit time:

1. **Risk classification** — a tool shaped `<provider>_<verb>_<noun>`
   (`register_targets`, `publish_sns_message`, `create_route53_record`, …) is
   missed by prefix auto-detection in `safety.py` and ships with no confirmation
   gate until an audit notices.
2. **Guardrail pipeline** — the 4-step `sanitize → block-check → validate →
   screen` sequence is hand-copied at 8 call sites with no shared helper.
3. **Tool execution paths** — `_handle_tool_uses` (chat), `approval_service`,
   `api_gateway`, `mcp` each re-derive context-setting and safety gating.

Phases 1–3 remove the defect: capability moves onto the tool, a real command
classifier replaces the regex list, and one `ToolExecutor.run()` becomes the only
path to a handler. Phases 4–7 are additive capability the spine unlocks.

| Phase | Scope | Status |
|---|---|---|
| 1 | Tool capability metadata | **shipped** |
| 2 | Command classifier | planned |
| 3 | Unified tool executor (choke point) | planned |
| 4 | Policy-as-YAML + environment identity | planned |
| 5 | Rollback stack | planned |
| 6 | Stateful MockWorld + behavioural CI | planned |
| 7 | Evidence-graph RCA | planned (optional) |

## Phase 1 — shipped

Branch `feat/tool-capability-metadata`.

Risk lives on the tool now, not only in the hand-maintained name-sets inside
`SafetyValidator.validate_tool_call`.

| Piece | What shipped |
|---|---|
| `src/agent/tool_capabilities.py` | The capability model (`permission` ladder `read < analyze < modify < deploy < destroy`, `mutating`, `reversible`, `produces`, `pentest`), the YAML loader, the module-declared registry, and `resolve(name)` — **module-declared > `config/tool_capabilities.yaml` > None**. |
| `config/tool_capabilities.yaml` | Backfill for 331 medium/high tools, **generated** by `scripts/gen_tool_capabilities.py` from `safety.py`'s current legacy classification (legacy `high` → `destroy`, `medium` → `modify`). Hand-tune individual entries as needed; inline `capability=` blocks override it. |
| `src/agent/core.py` | `register_tool(..., capability=...)` stores the block on `agent.tool_capabilities[name]` and calls `tool_capabilities.register_declared`. `register_tools_from_module` passes `tool.get('capability')` through. |
| `src/agent/safety.py` | `validate_tool_call` computes the legacy risk, then reconciles with `tool_capabilities.resolve(name)`: a declaration **raises** the level or holds it; a declaration more lenient than legacy is logged and ignored at runtime. New `legacy_risk_level(name)` helper and a `use_declared=False` kwarg expose the pure legacy path for the audit. |
| `scripts/audit_tool_capabilities.py` | `find_capability_gaps()` — the catalogue-wide guard. |
| `tests/test_tool_capabilities.py` | Unit tests for the model + resolution, and the guard wired into pytest (runs on every PR via `ci.yml`'s `test` job). |

### Invariants the guard enforces

Over the whole tool catalogue, excluding pentest tools and the action-aware
`manage_ec2_instance` / `manage_vm` / `manage_compute_instance` (which `safety.py`
classifies before the capability layer):

1. Any tool the legacy rules classify as medium/high **has** a resolved
   capability.
2. No resolved capability is **more lenient** than the legacy classification.
3. `validate_tool_call` never returns a lower risk than `legacy_risk_level` for
   the same tool.
4. `config/tool_capabilities.yaml` is not stale vs. the generator.

### What Phase 1 does NOT change

- The pentest gating and the three action-aware `manage_*` special cases in
  `safety.py` are untouched and still run first.
- Production escalation (`high` → `critical` when the input mentions prod) still
  lives in `safety.py`, applied after the capability resolves.
- The legacy name-sets stay in `safety.py` as the floor. They are removed in a
  later phase once every module declares inline.
- `mutating` / `reversible` / `produces` are recorded but not yet consumed —
  they feed the Phase 5 rollback stack and the session resource registry.

## Adding a new tool (updated)

When you add a `delete_*` / `update_*` / `create_*_rule` / IAM / `publish_*` /
`trigger_*` tool:

1. Add a `capability` block to its `get_tools()` entry, **or** run
   `python scripts/gen_tool_capabilities.py` to backfill
   `config/tool_capabilities.yaml`.
2. `tests/test_tool_capabilities.py` fails the build if a medium/high tool has
   neither. That is the safety net the old "remember to edit `safety.py`" step
   never had.

```python
{
    'name': 'delete_widget',
    'description': '...',
    'input_schema': {...},
    'handler': delete_widget,
    'capability': {'permission': 'destroy', 'mutating': True, 'reversible': False},
}
```

## Deferred

- Migrating each `src/tools/*_tools.py` from the generated YAML to inline
  `capability=` blocks (module by module, own PRs).
- Removing the legacy name-sets from `safety.py` (after the migration).
- `deploy` vs `modify` precision in the generated YAML — both map to `medium`
  today, so the distinction is currently cosmetic.
