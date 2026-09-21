#!/usr/bin/env python3
"""Governance-refactor Phase 1 guard: every risky tool must declare a capability.

``CLAUDE.md`` documents the recurring failure this closes — a tool shaped
``<provider>_<verb>_<noun>`` slips past prefix auto-detection and ships with no
confirmation gate until a later scheduled audit catches it. Once risk lives on
the tool (an entry in ``config/tool_capabilities.yaml`` or an inline
``capability=`` block), this check fails the build the moment a new medium/high
tool is added without one.

Two invariants, over the whole tool catalogue (excluding pentest tools and the
action-aware ``manage_*`` tools, which ``safety.py`` classifies before the
capability layer):

  1. Any tool the legacy rules classify as medium/high has a resolved capability.
  2. No resolved capability is *more lenient* than the legacy classification.

Wired into pytest via ``tests/test_tool_capabilities.py`` so it runs on every PR
through ``ci.yml``'s ``test`` job. Run standalone for the full list:

    python scripts/audit_tool_capabilities.py
"""
from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.agent import tool_capabilities  # noqa: E402
from src.agent.safety import SafetyValidator  # noqa: E402

TOOL_MODULES = (
    "command_tools", "aws_tools", "azure_tools", "gcp_tools", "kubernetes_tools",
    "git_tools", "github_tools", "docker_tools", "cicd_tools", "terraform_tools",
    "monitoring_tools", "ansible_tools", "alerting_tools", "pentest_tools",
    "sonarqube_tools", "nexus_tools", "devops_operations_tools",
)

ACTION_AWARE = {"manage_ec2_instance", "manage_vm", "manage_compute_instance"}
PENTEST_TOOLS = {
    "nmap_port_scan", "nmap_service_detection", "nikto_web_scan", "ssl_scan",
    "sqlmap_scan", "xss_scan", "zap_spider_scan", "quick_vulnerability_scan",
    "aws_security_audit", "azure_security_audit", "gcp_security_audit",
    "kubernetes_security_audit",
}
EXCLUDE = ACTION_AWARE | PENTEST_TOOLS

_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class Gap:
    tool: str
    kind: str  # "missing" | "lenient"
    detail: str


def all_tool_names() -> set[str]:
    names: set[str] = set()
    for modname in TOOL_MODULES:
        mod = importlib.import_module(f"src.tools.{modname}")
        for tool in mod.get_tools():
            names.add(tool["name"])
    return names


def find_capability_gaps() -> list[Gap]:
    sv = SafetyValidator()
    gaps: list[Gap] = []
    for name in sorted(all_tool_names() - EXCLUDE):
        legacy = sv.legacy_risk_level(name)
        cap = tool_capabilities.resolve(name)
        if legacy in ("medium", "high") and cap is None:
            gaps.append(Gap(name, "missing", f"legacy classifies '{legacy}', no declared capability"))
        elif cap is not None and _RANK[cap.risk()] < _RANK[legacy]:
            gaps.append(Gap(name, "lenient", f"declares '{cap.risk()}' ({cap.source}) < legacy '{legacy}'"))
    return gaps


def main() -> int:
    gaps = find_capability_gaps()
    if not gaps:
        print(f"OK — every risky tool has a capability at least as strict as the legacy rules")
        return 0
    missing = [g for g in gaps if g.kind == "missing"]
    lenient = [g for g in gaps if g.kind == "lenient"]
    if missing:
        print(f"\n{len(missing)} tool(s) with NO declared capability "
              f"(add to config/tool_capabilities.yaml — run scripts/gen_tool_capabilities.py):")
        for g in missing:
            print(f"  {g.tool:40s} {g.detail}")
    if lenient:
        print(f"\n{len(lenient)} declared capability(ies) more lenient than the legacy rules "
              f"(fix the YAML entry or the legacy set in safety.py):")
        for g in lenient:
            print(f"  {g.tool:40s} {g.detail}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
