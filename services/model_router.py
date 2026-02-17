"""
Tiered AI Model Router

Maps subscription tiers to AI providers and models.
Free users get Groq (no tool use), paid users get progressively better Claude models.
"""

import os
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ModelConfig:
    provider: str       # 'groq' or 'anthropic'
    model: str          # e.g. 'llama-3.3-70b-versatile', 'claude-haiku-4-5-20251001'
    display_name: str   # Human-readable name for UI
    supports_tools: bool
    max_tokens: int = 4096


# Default tier -> model mapping
DEFAULT_TIER_MODELS = {
    'free': ModelConfig(
        provider='groq',
        model='llama-3.3-70b-versatile',
        display_name='Llama 3.3 70B',
        supports_tools=False,
        max_tokens=4096,
    ),
    'starter': ModelConfig(
        provider='anthropic',
        model='claude-haiku-4-5-20251001',
        display_name='Claude Haiku 4.5',
        supports_tools=True,
        max_tokens=4096,
    ),
    'professional': ModelConfig(
        provider='anthropic',
        model='claude-sonnet-4-5-20250929',
        display_name='Claude Sonnet 4.5',
        supports_tools=True,
        max_tokens=8192,
    ),
    'business': ModelConfig(
        provider='anthropic',
        model='claude-opus-4-6',
        display_name='Claude Opus 4.6',
        supports_tools=True,
        max_tokens=8192,
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
    supports_tools = provider == 'anthropic'
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
