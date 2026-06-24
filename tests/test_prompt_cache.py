"""Tests for Anthropic prompt-caching helpers (src/agent/prompt_cache.py)."""
from src.agent.prompt_cache import build_cached_system


def test_build_cached_system_tags_core_not_tail():
    blocks = build_cached_system("CORE", "TAIL")
    assert blocks == [
        {"type": "text", "text": "CORE", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "TAIL"},
    ]


def test_build_cached_system_omits_empty_tail():
    for empty in (None, ""):
        blocks = build_cached_system("CORE", empty)
        assert len(blocks) == 1
        assert blocks[0] == {"type": "text", "text": "CORE", "cache_control": {"type": "ephemeral"}}


# ---------------------------------------------------------------------------
# Task 2 — build_volatile_tail
# ---------------------------------------------------------------------------
from src.agent.prompt_cache import build_volatile_tail


def test_volatile_tail_defaults_when_empty():
    expected = "User Preferences and Context:\nNo specific preferences set."
    assert build_volatile_tail(None) == expected
    assert build_volatile_tail("") == expected


def test_volatile_tail_with_prefs():
    assert build_volatile_tail("PREFS") == "User Preferences and Context:\nPREFS"


def test_volatile_tail_with_prefs_and_trial():
    assert build_volatile_tail("PREFS", "TRIAL") == "User Preferences and Context:\nPREFS\n\nTRIAL"
