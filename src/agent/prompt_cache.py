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


def build_volatile_tail(preferences: Optional[str], trial_context: Optional[str] = None) -> str:
    """Build the volatile (uncached) tail of the system prompt.

    Reproduces the legacy behavior: a 'No specific preferences set.' default and
    a trial-context block appended with a blank-line separator. Kept byte-identical
    so the joined `STABLE_SYSTEM_PROMPT + "\\n\\n" + tail` equals the pre-refactor
    system prompt.
    """
    prefs = preferences or "No specific preferences set."
    tail = f"User Preferences and Context:\n{prefs}"
    if trial_context:
        tail += f"\n\n{trial_context}"
    return tail


def apply_message_breakpoint(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Breakpoint 2: tag the last content block of the last message with
    cache_control. Returns a new list whose last message (and its content) is
    deep-copied, so the caller's stored history is never mutated. A string
    `content` is normalized into a one-block list first. No-op on empty input.
    """
    if not messages:
        return messages
    out = list(messages)
    last = copy.deepcopy(out[-1])
    content = last.get("content")
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
        last["content"] = content
    if not isinstance(content, list) or not content:
        out[-1] = last
        return out
    # Tag only when the last block is a dict; a non-dict trailing block is left
    # untagged (no breakpoint) rather than raising — silent skip is intentional.
    if isinstance(content[-1], dict):
        content[-1]["cache_control"] = dict(_EPHEMERAL)
    out[-1] = last
    return out
