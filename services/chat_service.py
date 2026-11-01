"""
Chat Service - Shared chat processing helpers.

Extracted from app.py to avoid circular imports when used by API v1 endpoints.
"""

import logging

logger = logging.getLogger(__name__)

FREE_TIER_SYSTEM_PROMPT = """You are a DevOps assistant running on a fallback model. You can answer questions about cloud infrastructure, Kubernetes, CI/CD, and DevOps best practices.

Note: The primary AI model is temporarily unavailable. Tool execution is not available in this fallback mode.

Provide helpful, accurate DevOps guidance based on the user's question."""

_ANTHROPIC_FAIL_PATTERNS = [
    'credit balance is too low',
    'Error communicating with Claude',
    'Error communicating with Kimi',
    '❌ Unexpected error',  # emoji-prefixed: matches the agent's own error (core.py) without
                            # catching legitimate responses that mention "unexpected error"
    'Rate limit reached',
    'Temporary API issue',
    # NOTE: 'API error:' removed — it false-matched legitimate tool results
    # (e.g. PagerDuty/OpsGenie handlers return "API error: ...") and wrongly
    # triggered Anthropic failover / the upgrade pitch.
    'overloaded_error',
    'insufficient balance',
]


def fallback_failure_message(primary_provider: str, primary_error: str) -> str:
    """Plain words for when the main model failed and the backup model failed too.

    Replaces the backup provider's raw exception text (for example a Groq
    "Error code: 401 - {...}"), which named the wrong service and helped nobody.
    """
    name = 'Claude' if primary_provider == 'anthropic' else 'Kimi'
    err = (primary_error or '').lower()
    if 'credit balance' in err or 'insufficient balance' in err:
        reason = f'the {name} account is out of credits'
    elif 'rate limit' in err:
        reason = f'the {name} account reached its rate limit'
    elif 'overloaded' in err or 'temporary api issue' in err:
        reason = f'{name} is overloaded right now'
    else:
        reason = f'{name} returned an error'
    return (f"{name} couldn't answer this time ({reason}), and the backup model isn't "
            f"available either. Nothing was changed. Please try again in a minute.")


def is_anthropic_error(text: str) -> bool:
    """Check if a response string is actually an Anthropic API error caught by the agent."""
    if not text:
        return False
    for pattern in _ANTHROPIC_FAIL_PATTERNS:
        if pattern in text:
            return True
    return False


EMPTY_ASSISTANT_PLACEHOLDER = "(No response text was generated for this turn.)"


def ensure_non_empty_response(text: str) -> str:
    """Substitute a placeholder for an empty/whitespace-only assistant response.

    An assistant turn with no closing text (e.g. a tool-only reply) must never be
    persisted to ChatMessage.content as-is: reloaded into a later turn's history, an
    empty assistant message breaks Kimi's API ("message ... must not be empty") and
    is rejected by Anthropic's API the same way. Every save point that writes a
    ChatMessage(role='assistant', ...) from agent-generated text must route through
    this helper. See CLAUDE_RUNBOOK.md's 2026-08-25 entry.
    """
    if not text or not text.strip():
        return EMPTY_ASSISTANT_PLACEHOLDER
    return text


GROQ_FALLBACK_MODEL = 'llama-3.3-70b-versatile'
GROQ_FALLBACK_MAX_TOKENS = 4096


def generate_upgrade_pitch(refills_at=None, in_app: bool = False) -> str:
    """Markdown shown when a Free-plan user has used this month's 20 credits.

    The Free plan refills every month (decided 2026-10-14); this used to call it a
    one-time trial that had "ended". Inside the iPhone app (``in_app``) it only says when
    the credits refill: the app shows no plans, prices or upgrade links (App Store rules).
    """
    from services.subscription_tiers import TIER_DEFINITIONS
    starter = next((t for t in TIER_DEFINITIONS if t['name'] == 'starter'), None)
    when = f" on **{refills_at:%B} {refills_at.day}**" if refills_at else " next month"
    lines = [
        "## You've used this month's free credits",
        "",
        f"Your 20 free credits refill{when}. Your conversations and settings are saved.",
    ]
    if starter and not in_app:
        lines += [
            "",
            "### Want to keep going now?",
            "",
            f"**Starter Plan: ${starter['monthly_price']:.0f}/month**",
            *[f"- {f}" for f in starter['features']],
            "",
            "[Upgrade](/billing) to pick up right where you left off.",
        ]
    return "\n".join(lines)


def process_free_tier_chat(message: str, conversation_history: list, preferences_context: str = None) -> str:
    """Process a chat message using Groq as Anthropic fallback (no tool use)."""
    from services.model_failover import get_groq_provider

    groq = get_groq_provider()

    system = FREE_TIER_SYSTEM_PROMPT
    if preferences_context:
        system += f"\n\nUser context:\n{preferences_context}"

    messages = list(conversation_history)
    if not messages or messages[-1].get('content') != message:
        messages.append({'role': 'user', 'content': message})

    return groq.chat(messages, system=system, model=GROQ_FALLBACK_MODEL, max_tokens=GROQ_FALLBACK_MAX_TOKENS)


def stream_free_tier_chat(message: str, conversation_history: list, preferences_context: str = None):
    """Stream a chat response using Groq as Anthropic fallback (no tool use)."""
    from services.model_failover import get_groq_provider

    groq = get_groq_provider()

    system = FREE_TIER_SYSTEM_PROMPT
    if preferences_context:
        system += f"\n\nUser context:\n{preferences_context}"

    messages = list(conversation_history)
    if not messages or messages[-1].get('content') != message:
        messages.append({'role': 'user', 'content': message})

    yield from groq.chat_stream(messages, system=system, model=GROQ_FALLBACK_MODEL, max_tokens=GROQ_FALLBACK_MAX_TOKENS)
