"""
Chat Service - Shared chat processing helpers.

Extracted from app.py to avoid circular imports when used by API v1 endpoints.
"""

import logging

logger = logging.getLogger(__name__)

FREE_TIER_SYSTEM_PROMPT = """You are a DevOps assistant. You can answer questions about cloud infrastructure, Kubernetes, CI/CD, and DevOps best practices.

Note: You are running on the free tier, which provides AI chat advice only. You cannot execute cloud operations or use tools directly.

To unlock full infrastructure automation (create/manage resources, run security scans, cost optimization, compliance checks), upgrade to a paid plan.

Provide helpful, accurate DevOps guidance based on the user's question."""

_ANTHROPIC_FAIL_PATTERNS = [
    'credit balance is too low',
    'Error communicating with Claude',
    'Unexpected error',
    'Rate limit reached',
    'Temporary API issue',
    'API error:',
    'overloaded_error',
]


def is_anthropic_error(text: str) -> bool:
    """Check if a response string is actually an Anthropic API error caught by the agent."""
    if not text:
        return False
    for pattern in _ANTHROPIC_FAIL_PATTERNS:
        if pattern in text:
            return True
    return False


def process_free_tier_chat(message: str, conversation_history: list, preferences_context: str = None) -> str:
    """Process a chat message using Groq for free-tier users (no tool use)."""
    from services.model_failover import get_groq_provider
    from services.model_router import resolve_model_for_tier

    model_config = resolve_model_for_tier('free')
    groq = get_groq_provider()

    system = FREE_TIER_SYSTEM_PROMPT
    if preferences_context:
        system += f"\n\nUser context:\n{preferences_context}"

    messages = list(conversation_history)
    if not messages or messages[-1].get('content') != message:
        messages.append({'role': 'user', 'content': message})

    return groq.chat(messages, system=system, model=model_config.model, max_tokens=model_config.max_tokens)


def stream_free_tier_chat(message: str, conversation_history: list, preferences_context: str = None):
    """Stream a chat response using Groq for free-tier users (no tool use)."""
    from services.model_failover import get_groq_provider
    from services.model_router import resolve_model_for_tier

    model_config = resolve_model_for_tier('free')
    groq = get_groq_provider()

    system = FREE_TIER_SYSTEM_PROMPT
    if preferences_context:
        system += f"\n\nUser context:\n{preferences_context}"

    messages = list(conversation_history)
    if not messages or messages[-1].get('content') != message:
        messages.append({'role': 'user', 'content': message})

    yield from groq.chat_stream(messages, system=system, model=model_config.model, max_tokens=model_config.max_tokens)
