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
    'Unexpected error',
    'Rate limit reached',
    'Temporary API issue',
    'API error:',
    'overloaded_error',
    'insufficient balance',
]


def is_anthropic_error(text: str) -> bool:
    """Check if a response string is actually an Anthropic API error caught by the agent."""
    if not text:
        return False
    for pattern in _ANTHROPIC_FAIL_PATTERNS:
        if pattern in text:
            return True
    return False


GROQ_FALLBACK_MODEL = 'llama-3.3-70b-versatile'
GROQ_FALLBACK_MAX_TOKENS = 4096


def generate_upgrade_pitch() -> str:
    """Return a markdown upgrade pitch for free-tier users who exhausted their trial credits."""
    return """## Your free trial has ended

You've used all **20 trial credits** -- and you got the full experience: the same AI agent and real cloud tools that our paid users rely on every day.

Here's what you accomplished during your trial:
- **Real tool execution** -- not just chat, actual cloud operations
- **AI-powered DevOps automation** with Kimi K2.5
- **Security scans, cost analysis, infrastructure management** -- all hands-free

### Ready to keep going?

**Starter Plan -- $29/month**
- 200 credits/month
- Full tool access (AWS, Azure, GCP, Kubernetes)
- Priority support

[Upgrade now](/billing) to pick up right where you left off. Your conversations and settings are saved."""


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
