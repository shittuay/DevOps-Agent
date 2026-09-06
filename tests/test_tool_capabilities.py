"""Governance refactor, Phase 1 — declared tool capability metadata.

Two layers:

  * unit tests for src/agent/tool_capabilities.py (resolution order, risk map,
    tolerance of malformed entries);
  * the catalogue-wide guard from scripts/audit_tool_capabilities.py — every
    medium/high tool has a declared capability, and no declaration is more
    lenient than safety.py's legacy classification. This is what fails the
    build when a new risky tool is added without a capability.

If the catalogue guard fails on a tool you added: run
``python scripts/gen_tool_capabilities.py`` to backfill config/tool_capabilities.yaml,
or add a ``capability`` block to the tool's ``get_tools()`` entry. Do not weaken
this test to make it pass.
"""
import textwrap

import pytest

from src.agent import tool_capabilities
from src.agent.safety import SafetyValidator
from scripts.audit_tool_capabilities import (
    all_tool_names,
    find_capability_gaps,
    EXCLUDE,
)

_RANK = {"low": 0, "medium": 1, "high": 2}


@pytest.fixture(autouse=True)
def _isolate_declared_registry():
    """Keep module-declared capabilities from one test out of the next."""
    tool_capabilities.clear_declared()
    tool_capabilities.reload_config()
    yield
    tool_capabilities.clear_declared()
    tool_capabilities.reload_config()


# --------------------------------------------------------------------------
# unit: the capability model
# --------------------------------------------------------------------------
class TestCapabilityModel:
    def test_permission_maps_to_risk(self):
        mk = lambda p: tool_capabilities._coerce("t", {"permission": p}, "test")
        assert mk("read").risk() == "low"
        assert mk("analyze").risk() == "low"
        assert mk("modify").risk() == "medium"
        assert mk("deploy").risk() == "medium"
        assert mk("destroy").risk() == "high"

    def test_requires_confirmation(self):
        mk = lambda p: tool_capabilities._coerce("t", {"permission": p}, "test")
        assert mk("read").requires_confirmation() is False
        assert mk("modify").requires_confirmation() is True
        assert mk("destroy").requires_confirmation() is True

    def test_pentest_forces_confirmation(self):
        cap = tool_capabilities._coerce("t", {"permission": "analyze", "pentest": True}, "test")
        assert cap.requires_confirmation() is True

    def test_mutating_defaults_from_permission(self):
        assert tool_capabilities._coerce("t", {"permission": "destroy"}, "x").mutating is True
        assert tool_capabilities._coerce("t", {"permission": "read"}, "x").mutating is False
        # explicit override wins
        assert tool_capabilities._coerce("t", {"permission": "destroy", "mutating": False}, "x").mutating is False

    def test_malformed_entries_are_ignored(self):
        assert tool_capabilities._coerce("t", {"permission": "nonsense"}, "x") is None
        assert tool_capabilities._coerce("t", {}, "x") is None
        assert tool_capabilities._coerce("t", "not-a-dict", "x") is None


# --------------------------------------------------------------------------
# unit: resolution order
# --------------------------------------------------------------------------
class TestResolution:
    def test_config_backfill_resolves(self):
        # delete_vpc is in the generated YAML
        cap = tool_capabilities.resolve("delete_vpc")
        assert cap is not None and cap.risk() == "high" and cap.source == "config"

    def test_unknown_tool_resolves_none(self):
        assert tool_capabilities.resolve("list_ec2_instances_totally_readonly") is None

    def test_declared_overrides_config(self):
        tool_capabilities.register_declared("delete_vpc", {"permission": "modify"})
        cap = tool_capabilities.resolve("delete_vpc")
        assert cap.risk() == "medium" and cap.source == "declared"

    def test_register_declared_ignores_empty(self):
        tool_capabilities.register_declared("whatever", None)
        tool_capabilities.register_declared("whatever", {})
        assert tool_capabilities.resolve("whatever") is None


# --------------------------------------------------------------------------
# unit: safety.py reconciliation
# --------------------------------------------------------------------------
class TestSafetyReconciliation:
    def test_declared_capability_raises_low_tool(self):
        sv = SafetyValidator()
        name = "totally_new_read_tool"
        assert sv.validate_tool_call(name, {}).risk_level == "low"
        tool_capabilities.register_declared(name, {"permission": "destroy"})
        result = sv.validate_tool_call(name, {})
        assert result.risk_level == "high"
        assert result.requires_confirmation is True
        assert "declared" in result.reason

    def test_lenient_declaration_does_not_downgrade(self, caplog):
        sv = SafetyValidator()
        # delete_vpc is legacy-high; a bad declaration must not lower it
        tool_capabilities.register_declared("delete_vpc", {"permission": "read"})
        result = sv.validate_tool_call("delete_vpc", {})
        assert result.risk_level == "high"
        assert "declares 'low'" in caplog.text

    def test_use_declared_false_gives_pure_legacy(self):
        sv = SafetyValidator()
        name = "another_new_tool"
        tool_capabilities.register_declared(name, {"permission": "destroy"})
        assert sv.validate_tool_call(name, {}, use_declared=False).risk_level == "low"
        assert sv.validate_tool_call(name, {}).risk_level == "high"

    def test_production_still_escalates_declared_high(self):
        sv = SafetyValidator()
        name = "new_prod_tool"
        tool_capabilities.register_declared(name, {"permission": "destroy"})
        result = sv.validate_tool_call(name, {"cluster": "production-db"})
        assert result.risk_level == "critical"


# --------------------------------------------------------------------------
# catalogue-wide guard
# --------------------------------------------------------------------------
class TestCatalogueGuard:
    def test_every_risky_tool_has_a_capability_at_least_as_strict(self):
        gaps = find_capability_gaps()
        assert not gaps, "\n" + textwrap.indent(
            "\n".join(f"{g.kind:8s} {g.tool}: {g.detail}" for g in gaps),
            "  ",
        ) + (
            "\n\nRun `python scripts/gen_tool_capabilities.py` to backfill "
            "config/tool_capabilities.yaml, or add a `capability` block to the "
            "tool's get_tools() entry."
        )

    def test_validate_tool_call_never_downgrades_a_tool(self):
        sv = SafetyValidator()
        downgraded = []
        for name in sorted(all_tool_names() - EXCLUDE):
            legacy = sv.legacy_risk_level(name)
            got = sv.validate_tool_call(name, {})
            got_lvl = "high" if got.risk_level in ("high", "critical") else got.risk_level
            if _RANK[got_lvl] < _RANK[legacy]:
                downgraded.append(f"{name}: got {got_lvl}, legacy {legacy}")
        assert not downgraded, "\n" + "\n".join(downgraded)

    def test_generated_yaml_is_not_stale(self):
        from scripts.gen_tool_capabilities import build_yaml, YAML_PATH
        assert YAML_PATH.read_text(encoding="utf-8") == build_yaml(), (
            "config/tool_capabilities.yaml is stale — run "
            "`python scripts/gen_tool_capabilities.py`"
        )
