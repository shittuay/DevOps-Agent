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


# ---------------------------------------------------------------------------
# Task 3 — apply_message_breakpoint (with non-mutation guarantee)
# ---------------------------------------------------------------------------
from src.agent.prompt_cache import apply_message_breakpoint
from src.agent.conversation import ConversationManager


def test_empty_list_noop():
    assert apply_message_breakpoint([]) == []


def test_string_content_normalized_and_tagged():
    msgs = [{"role": "user", "content": "hi"}]
    out = apply_message_breakpoint(msgs)
    assert out[-1]["content"] == [
        {"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}
    ]
    assert msgs[-1]["content"] == "hi"  # input not mutated


def test_last_block_of_block_list_tagged():
    msgs = [{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "RESULT"},
    ]}]
    out = apply_message_breakpoint(msgs)
    assert out[-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}


def test_does_not_mutate_stored_history():
    """Load-bearing: get_messages_for_api() shares content references, so tagging
    must deep-copy. Otherwise cache_control accumulates into stored history across
    the tool loop and exceeds the 4-breakpoint limit -> 400."""
    mgr = ConversationManager(max_history=100)
    mgr.add_user_message("hello")
    mgr.add_assistant_message([{"type": "tool_use", "id": "t1", "name": "x", "input": {}}])
    mgr.add_tool_result("t1", "RESULT")

    tagged = apply_message_breakpoint(mgr.get_messages_for_api())
    assert tagged[-1]["content"][-1].get("cache_control") == {"type": "ephemeral"}

    for m in mgr.get_messages_for_api():
        c = m["content"]
        if isinstance(c, list):
            for block in c:
                assert "cache_control" not in block


def test_none_content_returns_message_untouched():
    msgs = [{"role": "assistant", "content": None}]
    out = apply_message_breakpoint(msgs)
    assert out[-1]["content"] is None


def test_non_dict_last_block_skipped_silently():
    msgs = [{"role": "user", "content": [{"type": "text", "text": "a"}, "raw-string"]}]
    out = apply_message_breakpoint(msgs)
    # last block is a non-dict string -> no breakpoint applied, no crash
    assert out[-1]["content"][-1] == "raw-string"
    assert "cache_control" not in out[-1]["content"][0]


def test_only_last_message_copied_earlier_shared():
    earlier = {"role": "user", "content": [{"type": "text", "text": "keep"}]}
    msgs = [earlier, {"role": "user", "content": [{"type": "text", "text": "tag"}]}]
    out = apply_message_breakpoint(msgs)
    # earlier messages are the SAME objects (only the last is deep-copied)
    assert out[0] is earlier
    assert out[-1] is not msgs[-1]
    assert out[-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in earlier["content"][-1]


# ---------------------------------------------------------------------------
# Task 4 — STABLE_SYSTEM_PROMPT structural check
# ---------------------------------------------------------------------------


def test_stable_system_prompt_has_no_volatile_markers():
    from src.agent.core import STABLE_SYSTEM_PROMPT
    assert "{preferences}" not in STABLE_SYSTEM_PROMPT
    assert "User Preferences and Context:" not in STABLE_SYSTEM_PROMPT
    assert not STABLE_SYSTEM_PROMPT.endswith("\n")
    assert len(STABLE_SYSTEM_PROMPT) > 2000


# ---------------------------------------------------------------------------
# Call-site integration — assert the assembled api_params shape at _call_claude_api
# (closes the gap between the pure-helper unit tests and the real call site)
# ---------------------------------------------------------------------------
from unittest.mock import MagicMock, patch


def _make_agent(prompt_cache_enabled: bool):
    """Build a DevOpsAgent with a mocked Anthropic client and a config whose
    `prompt_cache.enabled` resolves to the given value (other keys -> default)."""
    from src.agent.core import DevOpsAgent

    def cfg_get(key, default=None):
        if key == 'prompt_cache.enabled':
            return prompt_cache_enabled
        return default

    cfg = MagicMock()
    cfg.get.side_effect = cfg_get
    cfg.claude_model = 'claude-sonnet-4-6'
    cfg.claude_max_tokens = 4096
    cfg.claude_temperature = 0.0
    with patch('src.agent.core.anthropic.Anthropic'):
        agent = DevOpsAgent(cfg)
    return agent


def _drive_call_claude_api(agent):
    """Stub the streaming client so one end_turn iteration runs, and return the
    api_params dict the agent passed to client.messages.stream(**api_params)."""
    fake_response = MagicMock()
    fake_response.stop_reason = 'end_turn'
    fake_response.content = [MagicMock(type='text', text='ok')]
    fake_response.usage = None  # _log_claude_usage short-circuits

    stream_cm = MagicMock()
    stream_cm.__enter__.return_value.get_final_message.return_value = fake_response
    agent.client.messages.stream.return_value = stream_cm

    agent.conversation.add_user_message("hello")
    agent._call_claude_api()
    return agent.client.messages.stream.call_args.kwargs


def _count_cache_control(api_params):
    n = 0
    system = api_params.get('system')
    if isinstance(system, list):
        n += sum(1 for b in system if isinstance(b, dict) and 'cache_control' in b)
    for msg in api_params.get('messages', []):
        content = msg.get('content')
        if isinstance(content, list):
            n += sum(1 for b in content if isinstance(b, dict) and 'cache_control' in b)
    return n


def test_call_site_enabled_emits_two_breakpoints():
    agent = _make_agent(prompt_cache_enabled=True)
    api_params = _drive_call_claude_api(agent)

    # system is a block list whose FIRST (stable-core) block carries bp1
    system = api_params['system']
    assert isinstance(system, list)
    assert system[0]['cache_control'] == {'type': 'ephemeral'}

    # bp2 sits on the last block of the last message
    assert api_params['messages'][-1]['content'][-1]['cache_control'] == {'type': 'ephemeral'}

    # exactly two breakpoints total — never approaches the 4-breakpoint ceiling
    assert _count_cache_control(api_params) == 2


def test_call_site_disabled_sends_plain_string_system_no_breakpoints():
    agent = _make_agent(prompt_cache_enabled=False)
    api_params = _drive_call_claude_api(agent)

    assert isinstance(api_params['system'], str)
    assert _count_cache_control(api_params) == 0
