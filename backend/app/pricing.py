"""Cost calculation for Thinklet.

Assumptions (documented for the demo — prices are approximate and meant for
relative comparison, not invoicing):

- Gemini's `usage_metadata.candidates_token_count` (what we call output_tokens)
  generally INCLUDES thinking/reasoning tokens. To avoid double-counting we
  price output_tokens at the output rate and only add thinking_tokens
  separately if the caller explicitly chose to track them outside of
  output_tokens (i.e. the SDK populated a non-null thinking_tokens that is
  *not* already inside output_tokens).
- For demo data we set thinking_tokens to None and bake the thinking cost
  into output_tokens, which mirrors the most common Gemini metadata shape.
- Rates below are placeholder USD/token values. They are deliberately small
  to keep totals readable on the dashboard; adjust here when real rates land.
"""
from __future__ import annotations

from dataclasses import dataclass

# Per-token USD rates. These are PLACEHOLDERS — see module docstring.
# Higher thinking levels cost more on the output side because they emit more
# (often hidden) tokens, which is exactly the waste pattern Thinklet detects.
_DEFAULT_INPUT_PRICE = 0.000_000_30   # $0.30 / 1M input tokens
_DEFAULT_OUTPUT_PRICE = 0.000_002_50  # $2.50 / 1M output tokens


@dataclass(frozen=True)
class ModelPricing:
    input_price_per_token: float
    output_price_per_token: float


PRICING_TABLE: dict[str, ModelPricing] = {
    "gemini-2.5-flash": ModelPricing(_DEFAULT_INPUT_PRICE, _DEFAULT_OUTPUT_PRICE),
    "gemini-2.5-pro": ModelPricing(
        input_price_per_token=0.000_001_25,    # $1.25 / 1M
        output_price_per_token=0.000_010_00,   # $10.00 / 1M
    ),
    # Gemini 3.x family — placeholder rates mirrored from 2.5; update with
    # published numbers when you have them.
    "gemini-3.5-flash": ModelPricing(_DEFAULT_INPUT_PRICE, _DEFAULT_OUTPUT_PRICE),
    "gemini-3.1-flash-lite": ModelPricing(_DEFAULT_INPUT_PRICE, _DEFAULT_OUTPUT_PRICE),
    "gemini-3-pro-preview": ModelPricing(
        input_price_per_token=0.000_001_25,
        output_price_per_token=0.000_010_00,
    ),
}


def _pricing_for(model: str) -> ModelPricing:
    return PRICING_TABLE.get(model, PRICING_TABLE["gemini-3.5-flash"])


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    thinking_tokens: int | None = None,
) -> float:
    """Return estimated USD cost for one call.

    Pricing logic:
      cost = input_tokens * input_price
           + output_tokens * output_price
           + (thinking_tokens or 0) * output_price   # only if thinking_tokens
                                                    # is reported SEPARATELY
                                                    # from output_tokens.

    For demo data we pass thinking_tokens=None so it doesn't add anything —
    the thinking burden is already inside output_tokens.
    """
    p = _pricing_for(model)
    cost = input_tokens * p.input_price_per_token
    cost += output_tokens * p.output_price_per_token
    if thinking_tokens:
        cost += thinking_tokens * p.output_price_per_token
    return round(cost, 8)
