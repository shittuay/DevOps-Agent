"""The agent labels prices it didn't read from a tool as estimates (owner request, 2026-10-15).

Seen in production: a GuardDuty answer quoted "~$1-5/mo" as if it were known.
"""
from src.agent.core import STABLE_SYSTEM_PROMPT


def test_system_prompt_requires_unverified_prices_to_be_labelled():
    rule = next(line for line in STABLE_SYSTEM_PROMPT.splitlines()
                if line.startswith('- PRICES ARE ESTIMATES'))
    assert 'tool result' in rule and '"estimate"' in rule and 'pricing page' in rule
    exec_block = STABLE_SYSTEM_PROMPT.split('=== EXECUTION INTEGRITY ===')[1].split('=== HARD LIMITS')[0]
    assert rule in exec_block
