"""
Tiered AI Model Router

Maps subscription tiers to AI providers and models.
Free and Starter users default to Kimi (cheaper, with tools).
Professional and Business users default to Claude (premium).
Users can override their tier default via preferred_model_provider.
"""

import os
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Moonshot Kimi model id, overridable via the KIMI_MODEL env var. Kept as one
# constant since the same default was drifting across independent call sites.
# kimi-k3.1-pro: released 2026-10-23, 1M context, tool calling, reasoning always on.
DEFAULT_KIMI_MODEL = 'kimi-k3.1-pro'
KIMI_DISPLAY_NAME = 'Kimi K3.1 Pro'
# Used if Moonshot refuses the configured model id (not found / not enabled for the key),
# so a model change can never take chat down for free and starter users.
KIMI_FALLBACK_MODEL = 'kimi-k3'


def kimi_model_unavailable(exc) -> bool:
    """True when the provider rejected the model id itself, not the request."""
    try:
        import openai
    except ImportError:
        return False
    if isinstance(exc, openai.NotFoundError):
        return True
    return isinstance(exc, openai.BadRequestError) and 'model' in str(exc).lower()


def kimi_create_with_fallback(client, params: dict):
    """chat.completions.create, retried once on KIMI_FALLBACK_MODEL if the model id is refused.

    Updates params['model'] in place so the caller keeps using the model that worked.
    """
    try:
        return client.chat.completions.create(**params)
    except Exception as exc:  # noqa: BLE001 - re-raised unless the model id was refused
        if params.get('model') == KIMI_FALLBACK_MODEL or not kimi_model_unavailable(exc):
            raise
        logger.warning("Kimi model %s unavailable (%s); falling back to %s",
                       params.get('model'), exc, KIMI_FALLBACK_MODEL)
        params['model'] = KIMI_FALLBACK_MODEL
        return client.chat.completions.create(**params)


@dataclass
class ModelConfig:
    provider: str       # 'anthropic', 'kimi', or 'groq'
    model: str          # e.g. 'kimi-k3.1-pro', 'claude-sonnet-4-6'
    display_name: str   # Human-readable name for UI
    supports_tools: bool
    max_tokens: int = 4096
    max_tools: int = 10          # max tools passed per API call (lower = less hallucination for Kimi)
    trust_tool_results: bool = True  # False for Kimi tiers — validates IDs before feeding back
    swarm_max_agents: int = 0    # Kimi swarm: 0 = disabled, >0 = max parallel sub-agents


# Kimi model config constant
KIMI_MODEL_CONFIG = ModelConfig(
    provider='kimi',
    model=DEFAULT_KIMI_MODEL,
    display_name=KIMI_DISPLAY_NAME,
    supports_tools=True,
    max_tokens=4096,
    max_tools=100,
    trust_tool_results=False,
    swarm_max_agents=20,
)

# Claude model configs for user overrides
CLAUDE_OVERRIDE_CONFIGS = {
    'free': ModelConfig(
        provider='anthropic',
        model='claude-sonnet-4-6',
        display_name='Claude Sonnet 4.6 (Trial)',
        supports_tools=True,
        max_tokens=4096,
        max_tools=100,
        trust_tool_results=True,
    ),
    'starter': ModelConfig(
        provider='anthropic',
        model='claude-haiku-4-5-20251001',
        display_name='Claude Haiku 4.5',
        supports_tools=True,
        max_tokens=4096,
        max_tools=100,
        trust_tool_results=True,
    ),
    'professional': ModelConfig(
        provider='anthropic',
        model='claude-sonnet-4-6',
        display_name='Claude Sonnet 4.6',
        supports_tools=True,
        max_tokens=8192,
        max_tools=60,
        trust_tool_results=True,
    ),
    'business': ModelConfig(
        provider='anthropic',
        model='claude-opus-4-6',
        display_name='Claude Opus 4.6',
        supports_tools=True,
        max_tokens=8192,
        max_tools=1000,
        trust_tool_results=True,
    ),
}

# Default tier -> model mapping
# Free + Starter default to Kimi (cheaper); Professional + Business default to Claude (premium)
DEFAULT_TIER_MODELS = {
    'free': ModelConfig(
        provider='kimi',
        model=DEFAULT_KIMI_MODEL,
        display_name=f'{KIMI_DISPLAY_NAME} (Trial)',
        supports_tools=True,
        max_tokens=4096,
        max_tools=100,
        trust_tool_results=False,
        swarm_max_agents=20,
    ),
    'starter': ModelConfig(
        provider='kimi',
        model=DEFAULT_KIMI_MODEL,
        display_name=KIMI_DISPLAY_NAME,
        supports_tools=True,
        max_tokens=4096,
        max_tools=100,
        trust_tool_results=False,
        swarm_max_agents=20,
    ),
    'professional': ModelConfig(
        provider='anthropic',
        model='claude-sonnet-4-6',
        display_name='Claude Sonnet 4.6',
        supports_tools=True,
        max_tokens=8192,
        max_tools=60,
        trust_tool_results=True,
    ),
    'business': ModelConfig(
        provider='anthropic',
        model='claude-opus-4-6',
        display_name='Claude Opus 4.6',
        supports_tools=True,
        max_tokens=8192,
        max_tools=1000,
        trust_tool_results=True,
    ),
}


def _parse_env_override(env_value: str) -> Optional[ModelConfig]:
    """Parse MODEL_TIER_<NAME>=provider:model env var override."""
    if ':' not in env_value:
        return None
    provider, model = env_value.split(':', 1)
    provider = provider.strip().lower()
    model = model.strip()
    if not provider or not model:
        return None
    supports_tools = provider in ('anthropic', 'kimi')
    return ModelConfig(
        provider=provider,
        model=model,
        display_name=model,
        supports_tools=supports_tools,
    )


def resolve_model_for_tier(tier_name: str) -> ModelConfig:
    """
    Resolve the AI model configuration for a subscription tier.

    Checks for env var override first (MODEL_TIER_FREE, MODEL_TIER_STARTER, etc.),
    then falls back to DEFAULT_TIER_MODELS.

    Args:
        tier_name: Subscription tier name (free, starter, professional, business)

    Returns:
        ModelConfig for the tier
    """
    tier_name = (tier_name or 'free').lower()

    env_key = f'MODEL_TIER_{tier_name.upper()}'
    env_val = os.environ.get(env_key)
    if env_val:
        override = _parse_env_override(env_val)
        if override:
            logger.info("Using env override for tier %s: %s:%s", tier_name, override.provider, override.model)
            return override

    config = DEFAULT_TIER_MODELS.get(tier_name)
    if config:
        return config

    # Unknown tier falls back to free
    logger.warning("Unknown tier '%s', falling back to free tier model", tier_name)
    return DEFAULT_TIER_MODELS['free']


def resolve_model_with_preference(tier_name: str, preferred_provider: Optional[str] = None) -> ModelConfig:
    """
    Resolve model config considering user's preferred provider override.

    If preferred_provider is set, returns an appropriate ModelConfig for that provider.
    Otherwise falls through to tier defaults via resolve_model_for_tier().

    Args:
        tier_name: Subscription tier name
        preferred_provider: User's preferred provider ('anthropic', 'kimi', or None for tier default)

    Returns:
        ModelConfig for the resolved provider
    """
    tier_name = (tier_name or 'free').lower()

    if preferred_provider == 'kimi':
        kimi_model = os.environ.get('KIMI_MODEL', DEFAULT_KIMI_MODEL)
        tier_defaults = DEFAULT_TIER_MODELS.get(tier_name, DEFAULT_TIER_MODELS['free'])
        return ModelConfig(
            provider='kimi',
            model=kimi_model,
            display_name=KIMI_DISPLAY_NAME,
            supports_tools=True,
            max_tokens=tier_defaults.max_tokens,
            max_tools=tier_defaults.max_tools,
            trust_tool_results=tier_defaults.trust_tool_results,
            swarm_max_agents=20,
        )

    if preferred_provider == 'anthropic':
        claude_config = CLAUDE_OVERRIDE_CONFIGS.get(tier_name)
        if claude_config:
            return claude_config
        return CLAUDE_OVERRIDE_CONFIGS['free']

    # No preference — use tier default
    return resolve_model_for_tier(tier_name)
