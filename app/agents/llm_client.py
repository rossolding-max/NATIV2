"""AsyncAnthropic singleton + cost telemetry helpers.

Single source for the Anthropic SDK client. Used by every Agent subclass via
``get_async_anthropic()``. Module-level singleton avoids per-call instantiation
overhead under Celery (per the M2 plan's "execution-time landmines" section).

Cost telemetry: pricing constants reflect the published rates for the model
family. Update on each minor SDK release (see CONTRIBUTING.md upgrade ritual).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from anthropic import AsyncAnthropic

from app.config import settings

# ── Pricing constants (USD per million tokens) ───────────────────────
# Per `claude-opus-4-7` published pricing. Cache-creation costs 1.25x base
# input; cache-read costs 0.1x base input. Reviewed on each Anthropic SDK
# minor bump per CONTRIBUTING.md.
#
# Source: https://docs.anthropic.com/en/api/pricing (verify at upgrade time).
_PRICE_OPUS_4_7_INPUT_PER_M_USD = Decimal("15.00")
_PRICE_OPUS_4_7_OUTPUT_PER_M_USD = Decimal("75.00")
_PRICE_OPUS_4_7_CACHE_CREATION_PER_M_USD = Decimal("18.75")  # 1.25x input
_PRICE_OPUS_4_7_CACHE_READ_PER_M_USD = Decimal("1.50")  # 0.1x input

_PRICING: dict[str, dict[str, Decimal]] = {
    "claude-opus-4-7": {
        "input": _PRICE_OPUS_4_7_INPUT_PER_M_USD,
        "output": _PRICE_OPUS_4_7_OUTPUT_PER_M_USD,
        "cache_creation": _PRICE_OPUS_4_7_CACHE_CREATION_PER_M_USD,
        "cache_read": _PRICE_OPUS_4_7_CACHE_READ_PER_M_USD,
    },
}

# ── Module-level singleton ────────────────────────────────────────────

_client: AsyncAnthropic | None = None


def get_async_anthropic() -> AsyncAnthropic:
    """Return the lazy-initialised ``AsyncAnthropic`` singleton.

    Reuses a single HTTP connection pool across all Agent invocations. Mirrors
    the M0 Langfuse client pattern. Closed implicitly on process exit.
    """
    global _client
    if _client is None:
        _client = AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
            timeout=float(settings.anthropic_request_timeout_seconds),
            max_retries=settings.anthropic_max_retries,
        )
    return _client


def reset_client_for_tests() -> None:
    """Reset the singleton (test-only helper).

    pytest fixtures call this when they need a fresh client (e.g. when
    monkeypatching the API key). Production code never calls this.
    """
    global _client
    _client = None


# ── Cost computation ──────────────────────────────────────────────────


def compute_cost_usd(model: str, usage: Any) -> Decimal:
    """Compute USD cost from a ``response.usage`` block.

    ``usage`` is the ``anthropic.types.Usage`` instance from a Messages API
    response. Returns ``Decimal("0.00")`` for unknown models (logged elsewhere).
    """
    pricing = _PRICING.get(model)
    if pricing is None:
        return Decimal("0.00")

    input_tok = Decimal(usage.input_tokens)
    output_tok = Decimal(usage.output_tokens)
    cache_creation = Decimal(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    cache_read = Decimal(getattr(usage, "cache_read_input_tokens", 0) or 0)

    million = Decimal("1_000_000")
    cost = (
        (input_tok / million) * pricing["input"]
        + (output_tok / million) * pricing["output"]
        + (cache_creation / million) * pricing["cache_creation"]
        + (cache_read / million) * pricing["cache_read"]
    )
    return cost.quantize(Decimal("0.000001"))


def extract_telemetry(model: str, usage: Any, latency_ms: int) -> dict[str, Any]:
    """Build a telemetry dict from a Messages API response usage block.

    Helper for ``Agent`` subclasses + the cost rollup tests.
    """
    return {
        "model": model,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "cost_usd": compute_cost_usd(model, usage),
        "latency_ms": latency_ms,
    }
