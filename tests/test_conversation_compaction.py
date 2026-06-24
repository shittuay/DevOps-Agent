"""Tests for token-aware context compaction in ConversationManager."""
from src.agent.conversation import ConversationManager, estimate_tokens


def _big_payload(i: int, words: int = 250) -> str:
    """Unique-ish content so token counts scale under both tiktoken and the
    len/4 heuristic (repeated chars would BPE-compress and skew tiktoken)."""
    return " ".join(f"resource-{i}-field-{k}-value{k * 3}" for k in range(words))


def _add_pairs(mgr: ConversationManager, n: int) -> None:
    for i in range(n):
        mgr.add_assistant_message([
            {'type': 'tool_use', 'id': f'tu{i}', 'name': 'list_resources', 'input': {}}
        ])
        mgr.add_tool_result(f'tu{i}', _big_payload(i))


def test_estimate_tokens_scales_with_length():
    short = estimate_tokens("hello world")
    long = estimate_tokens("hello world " * 100)
    assert short > 0
    assert long > short


def test_no_budget_preserves_legacy_behavior():
    """token_budget=None must not compact anything (existing behavior intact)."""
    mgr = ConversationManager(max_history=1000, token_budget=None)
    mgr.add_user_message("REMEMBER: prod cluster is prod-east-1")
    _add_pairs(mgr, 10)
    for msg in mgr.messages:
        for block in msg.content:
            if isinstance(block, dict) and block.get('type') == 'tool_result':
                assert '[compacted' not in block['content']


def test_compaction_reduces_tokens_and_preserves_structure():
    # Budget chosen to be achievable above the compacted floor while still far
    # below the uncompacted total, so compaction provably triggers.
    budget = 6000
    mgr = ConversationManager(max_history=1000, token_budget=budget, recency_keep=2)
    mgr.add_user_message("REMEMBER: prod cluster is prod-east-1")
    _add_pairs(mgr, 15)

    # Compaction actually happened.
    markers = sum(
        1 for msg in mgr.messages for block in msg.content
        if isinstance(block, dict) and block.get('type') == 'tool_result'
        and '[compacted' in block.get('content', '')
    )
    assert markers > 0

    # Achievable budget is respected.
    assert mgr.estimated_tokens() <= budget

    # tool_use / tool_result pairing is preserved (none orphaned).
    tool_uses = sum(
        1 for msg in mgr.messages for block in msg.content
        if isinstance(block, dict) and block.get('type') == 'tool_use'
    )
    tool_results = sum(
        1 for msg in mgr.messages for block in msg.content
        if isinstance(block, dict) and block.get('type') == 'tool_result'
    )
    assert tool_uses == tool_results == 15

    # Early context is retained (compacted, not dropped).
    first = mgr.messages[0]
    assert first.role == 'user'
    assert 'prod-east-1' in first.content[0]['text']


def test_recency_window_never_compacted():
    recency = 4
    mgr = ConversationManager(max_history=1000, token_budget=2000, recency_keep=recency)
    mgr.add_user_message("start")
    _add_pairs(mgr, 20)

    for msg in mgr.messages[-recency:]:
        for block in msg.content:
            if isinstance(block, dict) and block.get('type') == 'tool_result':
                assert '[compacted' not in block['content']
