"""Pure helpers for Anthropic prompt caching (Phase 2).

No I/O, no SDK calls — just builds the `cache_control` content-block structures
the Claude call sites in core.py pass to messages.stream(). Caching applies to
the Claude path only; Kimi (OpenAI-compatible) uses a different mechanism.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

_EPHEMERAL = {"type": "ephemeral"}


def build_cached_system(stable_core: str, volatile_tail: Optional[str]) -> List[Dict[str, Any]]:
    """Breakpoint 1: return Anthropic `system` as content blocks.

    The stable core carries the cache_control breakpoint (this also caches the
    tool schemas, which render before `system`). The volatile tail — when present
    — follows as an uncached block. Omitted entirely when the tail is empty.
    """
    blocks: List[Dict[str, Any]] = [
        {"type": "text", "text": stable_core, "cache_control": dict(_EPHEMERAL)}
    ]
    if volatile_tail:
        blocks.append({"type": "text", "text": volatile_tail})
    return blocks
