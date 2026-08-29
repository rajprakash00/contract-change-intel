"""Token→USD cost math. Pure functions; prices are the only mutable facts.

Pricing is USD per 1M tokens, matching OpenAI's published list prices at the
time of writing. When OpenAI changes prices or a model is added, update the
table and the literals in tests/test_llm_cost.py together.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    input_per_million: float
    output_per_million: float


_PRICES: dict[str, ModelPricing] = {
    "gpt-4o-mini": ModelPricing(input_per_million=0.15, output_per_million=0.60),
    "gpt-4o": ModelPricing(input_per_million=2.50, output_per_million=10.00),
}


def pricing_for(model: str) -> ModelPricing:
    """Raises LookupError for models without a declared price."""
    return _PRICES[model]


def cost_usd(model: str, *, prompt_tokens: int, completion_tokens: int) -> float:
    """Cost of one call in USD, from per-1M-token list prices."""
    pricing = pricing_for(model)
    return (
        prompt_tokens / 1_000_000 * pricing.input_per_million
        + completion_tokens / 1_000_000 * pricing.output_per_million
    )
