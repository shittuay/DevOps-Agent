"""Regression: paid tiers must resolve to the model their pricing advertises.

`business` ($299/mo) and `professional` ($99/mo) were both configured as
`claude-sonnet-4-6` in BOTH `DEFAULT_TIER_MODELS` and `CLAUDE_OVERRIDE_CONFIGS`,
while CLAUDE.md's tier table advertised `claude-opus-4-6` for business. Business
customers were paying 3x professional for an identical model, and nothing in the
suite noticed — every existing assertion about the business tier covered
`max_tools` and `trust_tool_results`, never the model itself.

This drift is silent by nature: the tier still works, requests still succeed,
and only the bill differs from what was sold. These tests pin the mapping so a
future edit to one dict (or to one tier and not its override) fails loudly.
"""
import pytest

from services.model_router import CLAUDE_OVERRIDE_CONFIGS, DEFAULT_TIER_MODELS

# The contract CLAUDE.md's "Model Tier Mapping" table advertises.
EXPECTED_PAID_MODELS = {
    'professional': 'claude-sonnet-4-6',
    'business': 'claude-opus-4-6',
}


@pytest.mark.parametrize('tier,expected_model', sorted(EXPECTED_PAID_MODELS.items()))
def test_default_tier_model_matches_advertised(tier, expected_model):
    assert DEFAULT_TIER_MODELS[tier].model == expected_model, (
        f"{tier} tier resolves to {DEFAULT_TIER_MODELS[tier].model!r}, but CLAUDE.md "
        f"advertises {expected_model!r} at that price point"
    )


@pytest.mark.parametrize('tier,expected_model', sorted(EXPECTED_PAID_MODELS.items()))
def test_claude_override_matches_advertised(tier, expected_model):
    """The override dict is what a user's explicit model toggle resolves to, so
    it has to agree with the default or the tier silently changes behavior
    depending on whether the toggle was ever touched."""
    assert CLAUDE_OVERRIDE_CONFIGS[tier].model == expected_model, (
        f"{tier} override resolves to {CLAUDE_OVERRIDE_CONFIGS[tier].model!r}, "
        f"expected {expected_model!r}"
    )


def test_business_is_not_the_same_model_as_professional():
    """The specific regression: business priced 3x professional for the same model."""
    business = DEFAULT_TIER_MODELS['business'].model
    professional = DEFAULT_TIER_MODELS['professional'].model
    assert business != professional, (
        f"business and professional both resolve to {business!r} — business is "
        "priced 3x professional, so an identical model means customers are "
        "paying for a tier they do not receive"
    )


def test_default_and_override_agree_for_every_paid_tier():
    for tier in EXPECTED_PAID_MODELS:
        assert DEFAULT_TIER_MODELS[tier].model == CLAUDE_OVERRIDE_CONFIGS[tier].model, (
            f"{tier}: default resolves to {DEFAULT_TIER_MODELS[tier].model!r} but "
            f"override resolves to {CLAUDE_OVERRIDE_CONFIGS[tier].model!r} — these "
            "must not diverge"
        )
