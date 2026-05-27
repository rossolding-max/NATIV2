"""Step 6 — brand-history industry inference.

For each ``previous_brands[]`` entry, derive ``industry_id``:

1. Exact match in ``data/brand_industry_map.json`` (fast, deterministic).
2. Exa search + LLM classification fallback (slower, paid).
3. User dropdown UI fallback (handled by the REST layer; this service
   doesn't trigger it).

On confirmed inference, the new (name → industry_id) pair is written back
to the seed map so future onboardings benefit (idempotent reimport).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.utils.logging import get_logger
from app.vendors.exa import ExaClient

log = get_logger(__name__)


@dataclass(frozen=True)
class IndustryInference:
    """Outcome of a brand → industry resolution."""

    brand_name: str
    industry_id: str | None
    confidence: float
    source: str  # "exact_match" | "exa_llm" | "unknown"


@lru_cache(maxsize=1)
def _load_brand_industry_map() -> dict[str, str]:
    """Load ``data/brand_industry_map.json`` and normalise keys.

    Returns ``{lowercase_brand_name: industry_id}``. Empty dict if the
    file is missing (dev / CI without the seed).
    """
    repo = Path(__file__).resolve().parents[2]
    path = repo / "data" / "brand_industry_map.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    items = raw.get("brands", raw) if isinstance(raw, dict) else raw
    if isinstance(items, dict):
        return {k.strip().lower(): v for k, v in items.items() if v}
    if isinstance(items, list):
        mapping: dict[str, str] = {}
        for entry in items:
            if not isinstance(entry, dict):
                continue
            name = entry.get("brand_name") or entry.get("name") or entry.get("brand")
            industry = entry.get("industry_id") or entry.get("industry")
            if name and industry:
                mapping[str(name).strip().lower()] = str(industry)
        return mapping
    return {}


def reset_cache_for_tests() -> None:
    _load_brand_industry_map.cache_clear()


def resolve_via_exact_match(brand_name: str) -> IndustryInference | None:
    """Try the deterministic seed-map first."""
    mapping = _load_brand_industry_map()
    industry = mapping.get(brand_name.strip().lower())
    if industry:
        return IndustryInference(
            brand_name=brand_name,
            industry_id=industry,
            confidence=1.0,
            source="exact_match",
        )
    return None


async def resolve_via_exa_llm(
    brand_name: str,
    *,
    exa_client: ExaClient | None = None,
) -> IndustryInference:
    """Exa search + light LLM classification.

    v0.1 implementation: query Exa for the brand domain, return UNKNOWN
    confidence so the UI surfaces a dropdown. The full LLM-classifier
    lands in M7 (Brand Discovery) where the prompt + cassettes get full
    coverage.
    """
    _ = exa_client  # client wired here in M7
    log.info("brand_industry_exa_fallback", brand=brand_name)
    return IndustryInference(
        brand_name=brand_name,
        industry_id=None,
        confidence=0.0,
        source="unknown",
    )


async def resolve_industry(brand_name: str) -> IndustryInference:
    """Three-step fallback: exact match → Exa+LLM → unknown."""
    if not brand_name.strip():
        return IndustryInference(
            brand_name=brand_name,
            industry_id=None,
            confidence=0.0,
            source="unknown",
        )
    exact = resolve_via_exact_match(brand_name)
    if exact is not None:
        return exact
    return await resolve_via_exa_llm(brand_name)


def merge_inference_into_brands(
    previous_brands: list[dict[str, Any]],
    inferences: list[IndustryInference],
) -> list[dict[str, Any]]:
    """Apply inferences back to the ``previous_brands[]`` array."""
    by_name = {inf.brand_name.strip().lower(): inf for inf in inferences}
    merged: list[dict[str, Any]] = []
    for brand in previous_brands:
        name = str(brand.get("brand") or brand.get("name") or "").strip().lower()
        inference = by_name.get(name)
        merged_entry = dict(brand)
        if inference is not None and inference.industry_id is not None:
            merged_entry["industry_id"] = inference.industry_id
            merged_entry["industry_inference_source"] = inference.source
            merged_entry["industry_inference_confidence"] = inference.confidence
        merged.append(merged_entry)
    return merged
