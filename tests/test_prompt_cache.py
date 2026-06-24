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
