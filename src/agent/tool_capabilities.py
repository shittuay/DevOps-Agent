"""Declared tool capability metadata — Phase 1 of the governance refactor.

Risk should live on the tool, not in a hand-maintained name-set inside
``safety.py``. ``CLAUDE.md`` documents the failure mode this replaces: a tool
shaped ``<provider>_<verb>_<noun>`` (``register_targets``, ``publish_sns_message``,
``create_route53_record`` …) is missed by prefix auto-detection and ships
ungated until a later scheduled audit notices.

Each tool may declare a ``capability`` block in its module's ``get_tools()``
entry. Anything not declared inline is backfilled from
``config/tool_capabilities.yaml``. ``safety.py`` resolves risk from this data
first and only falls back to its legacy name-set / pattern matching when a tool
has no declared capability at all — the legacy result stays a floor a
declaration can raise but never lower.

Resolution order (most specific wins):

    1. ``capability=`` passed to ``DevOpsAgent.register_tool()`` (module-declared)
    2. an entry under ``tools:`` in ``config/tool_capabilities.yaml``
    3. ``None`` — caller keeps its legacy classification

Capability shape::

    permission:  read | analyze | modify | deploy | destroy   (required)
    mutating:    bool   (default: True for modify/deploy/destroy, else False)
    reversible:  bool | null   (null = unknown; consumed by the Phase 5 rollback stack)
    produces:    str | null    (resource type a create-class tool yields)
    pentest:     bool  (default False)

See docs/governance-refactor.md.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)

# Permission ladder, least -> most privileged.
PERMISSION_LEVELS = ("read", "analyze", "modify", "deploy", "destroy")
_PERM_RANK = {p: i for i, p in enumerate(PERMISSION_LEVELS)}

# permission -> (safety.py risk_level, requires_confirmation). Production
# escalation (high -> critical) stays in safety.py; this map is environment-blind.
_PERM_TO_RISK: Dict[str, "tuple[str, bool]"] = {
    "read": ("low", False),
    "analyze": ("low", False),
    "modify": ("medium", True),
    "deploy": ("medium", True),
    "destroy": ("high", True),
}

_YAML_PATH = Path(__file__).resolve().parents[2] / "config" / "tool_capabilities.yaml"


@dataclass(frozen=True)
class Capability:
    """One tool's declared risk surface."""

    permission: str
    mutating: bool
    reversible: Optional[bool] = None
    produces: Optional[str] = None
    pentest: bool = False
    source: str = "declared"  # "declared" | "config"

    @property
    def rank(self) -> int:
        return _PERM_RANK[self.permission]

    def risk(self) -> str:
        """Map to safety.py's low/medium/high vocabulary (no production escalation)."""
        return _PERM_TO_RISK[self.permission][0]

    def requires_confirmation(self) -> bool:
        return _PERM_TO_RISK[self.permission][1] or self.pentest


def _coerce(name: str, raw: Any, source: str) -> Optional[Capability]:
    if not isinstance(raw, dict):
        logger.warning("tool_capabilities: entry for %r is not a mapping — ignoring", name)
        return None
    perm = str(raw.get("permission", "")).lower().strip()
    if perm not in _PERM_RANK:
        logger.warning(
            "tool_capabilities: %r has missing/invalid permission %r — ignoring", name, raw.get("permission")
        )
        return None
    mutating = raw.get("mutating")
    mutating = perm in ("modify", "deploy", "destroy") if mutating is None else bool(mutating)
    reversible = raw.get("reversible")
    if reversible is not None:
        reversible = bool(reversible)
    produces = raw.get("produces")
    return Capability(
        permission=perm,
        mutating=mutating,
        reversible=reversible,
        produces=str(produces) if produces else None,
        pentest=bool(raw.get("pentest", False)),
        source=source,
    )


# ---------------------------------------------------------------------------
# config-file backfill (loaded once, cached)
# ---------------------------------------------------------------------------
_config_cache: Optional[Dict[str, Capability]] = None


def _load_config() -> Dict[str, Capability]:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    out: Dict[str, Capability] = {}
    try:
        data = yaml.safe_load(_YAML_PATH.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        logger.warning("tool_capabilities: %s not found — config backfill disabled", _YAML_PATH)
        data = {}
    except Exception as exc:  # noqa: BLE001 — a broken YAML file must not take the agent down
        logger.error("tool_capabilities: failed to parse %s: %s", _YAML_PATH, exc)
        data = {}
    for name, raw in (data.get("tools") or {}).items():
        cap = _coerce(str(name), raw, source="config")
        if cap is not None:
            out[str(name)] = cap
    _config_cache = out
    return out


def reload_config() -> None:
    """Test hook: drop the cache so the next resolve re-reads the YAML."""
    global _config_cache
    _config_cache = None


# ---------------------------------------------------------------------------
# module-declared registry (populated by DevOpsAgent.register_tool)
# ---------------------------------------------------------------------------
_declared: Dict[str, Capability] = {}


def register_declared(name: str, capability: Optional[Dict[str, Any]]) -> None:
    """Record a capability block a tool module shipped in its ``get_tools()`` entry."""
    if not capability:
        return
    cap = _coerce(name, capability, source="declared")
    if cap is not None:
        _declared[name] = cap


def clear_declared() -> None:
    """Test hook."""
    _declared.clear()


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------
def resolve(tool_name: str) -> Optional[Capability]:
    """Module-declared capability > config backfill > ``None``."""
    if tool_name in _declared:
        return _declared[tool_name]
    return _load_config().get(tool_name)


def all_known() -> Dict[str, Capability]:
    """Every tool with a capability from either source (module-declared wins)."""
    merged: Dict[str, Capability] = dict(_load_config())
    merged.update(_declared)
    return merged
