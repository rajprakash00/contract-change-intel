"""Unit tests for token→USD cost math (pure logic, no I/O).

Pricing literals here are the independent source of truth; the module's table
must match published OpenAI list prices (USD per 1M tokens) for the models it
declares.
"""

import pytest

from app.llm.cost import ModelPricing, cost_usd, pricing_for


def test_gpt_4o_mini_cost_matches_published_pricing() -> None:
    # $0.15 / 1M input, $0.60 / 1M output.
    cost = cost_usd("gpt-4o-mini", prompt_tokens=1_000_000, completion_tokens=1_000_000)
    assert cost == pytest.approx(0.75)


def test_cost_scales_linearly_with_tokens() -> None:
    # $0.15 / 1M input → 1_500 input tokens cost $0.000225.
    cost = cost_usd("gpt-4o-mini", prompt_tokens=1_500, completion_tokens=0)
    assert cost == pytest.approx(0.000225)


def test_zero_tokens_cost_zero() -> None:
    assert cost_usd("gpt-4o-mini", prompt_tokens=0, completion_tokens=0) == 0.0


def test_unknown_model_raises_lookup_error() -> None:
    with pytest.raises(LookupError):
        pricing_for("totally-made-up-model")


def test_pricing_for_returns_declared_table_entry() -> None:
    pricing = pricing_for("gpt-4o-mini")
    assert isinstance(pricing, ModelPricing)
    assert pricing.input_per_million == pytest.approx(0.15)
    assert pricing.output_per_million == pytest.approx(0.60)
