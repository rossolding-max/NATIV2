"""M7.7 Phase 4 — Signal overlay (S15-global + S16 + S17).

These three searches refresh "what's happening this month" overlays on
top of the existing brand universe:

  - S15-residual — Industry-AGNOSTIC global trending funded brands.
    Today's M7.6 S15 keys queries on talent industries; the v2 form
    drops the industry seed and asks "what got funded this month
    globally that fits creator marketing?". Output goes into Phase 4.
  - S16 — last30days social trending (existing module, gated).
  - S17 — paid social spend signal (existing module, gated).

Runs on EVERY discovery run (maintenance + full_build) AND monthly via
Celery beat for active talents (wired in Commit 6).
"""

from __future__ import annotations

from typing import Any

from app.services.discovery import (
    search_16_last30days_trending,
    search_17_paid_social_signal,
)
from app.services.discovery._models import CandidateSource
from app.utils.logging import get_logger

log = get_logger(__name__)


_S15_RESIDUAL_TAG: str = "global_trending_funded"
_S15_RESIDUAL_BASE_WEIGHT: float = 0.15
_S15_RESIDUAL_MAX_WEIGHT: float = 0.25


def _global_trending_funded_queries(*, talent_country: str | None) -> list[str]:
    geo = f" {talent_country}" if talent_country else ""
    return [
        f"top recently funded brands{geo} 2026",
        f"viral newly launched DTC brands{geo} 2026",
        f"creator-marketing-friendly startups funded this month{geo}",
        f"YC-backed consumer brands{geo} 2026",
        f"a16z-backed consumer brands{geo} 2026",
        f"hot new D2C startups{geo} 2026",
        f"new brands raising Series A 2026{geo}",
    ]


async def _exa_global_funded(
    *,
    talent_country: str | None,
    results_per_query: int = 5,
) -> list[CandidateSource]:
    """Run the industry-agnostic global recently-funded sweep (S15 residual)."""
    queries = _global_trending_funded_queries(talent_country=talent_country)
    if not queries:
        return []

    from app.agents.llm_client import get_async_anthropic
    from app.config import settings
    from app.utils.slugify import slugify_brand_name
    from app.vendors.exa import ExaClient

    exa = ExaClient()
    client = get_async_anthropic()
    sources: list[CandidateSource] = []
    seen: set[tuple[str, str]] = set()  # (brand_id, query)

    for query in queries:
        try:
            resp = await exa.search(
                query,
                num_results=results_per_query,
                category="company",
                contents={"text": {"includeHtmlTags": False, "maxCharacters": 4000}},
            )
        except Exception as exc:
            log.warning("phase_4_s15_residual_failed", query=query, error=str(exc))
            continue
        raw_results = [r for r in (resp.get("results") or []) if isinstance(r, dict)]
        if not raw_results:
            continue

        # Reuse Phase 2's extraction prompt shape, but ask for "funded brand"
        # category with no industry constraint.
        blocks: list[str] = []
        for entry in raw_results:
            url = entry.get("url") or ""
            title = entry.get("title") or ""
            body = (entry.get("text") or entry.get("content") or "")[:4000]
            blocks.append(f"--- {title} ({url}) ---\n{body}")
        pages = "\n\n".join(blocks)
        prompt = (
            "You are reviewing web pages about recently-funded brands "
            "(industry agnostic). Extract BRAND names mentioned as recently "
            "funded, launched, or trending across creator marketing.\n\n"
            "Rules:\n"
            '- Output JSON: {"brands": [{"brand_name": str, '
            '"suggested_industry_id": str (best guess; or "uncategorised"), '
            '"confidence": float 0-1, "evidence": str (short quote), '
            '"source_url": str}]}.\n'
            "- ONLY include specific brand names — no generic categories.\n"
            "- Confidence 0.90+ = explicitly described; 0.70-0.89 = strong "
            "inference; below 0.70 = drop.\n"
            "- Return ONLY the JSON.\n\n"
            f"PAGES:\n\n{pages}\n"
        )
        try:
            response = await client.messages.create(
                model=settings.anthropic_default_model,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            log.warning("phase_4_s15_residual_llm_failed", query=query, error=str(exc))
            continue

        text_parts: list[str] = []
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", "") or "")
        # Inline minimal JSON parse — same shape as Phase 2.
        import json
        import re

        text = "".join(text_parts).strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            continue
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        for entry in data.get("brands") or []:
            if not isinstance(entry, dict):
                continue
            name = (entry.get("brand_name") or "").strip()
            confidence = entry.get("confidence")
            if not name or not isinstance(confidence, int | float) or confidence < 0.70:
                continue
            brand_id = slugify_brand_name(name)
            if brand_id == "unknown":
                continue
            dedup_key = (brand_id, query)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            weight = _S15_RESIDUAL_BASE_WEIGHT + (
                _S15_RESIDUAL_MAX_WEIGHT - _S15_RESIDUAL_BASE_WEIGHT
            ) * (float(confidence) - 0.70) / 0.30
            weight = max(_S15_RESIDUAL_BASE_WEIGHT, min(_S15_RESIDUAL_MAX_WEIGHT, weight))
            sources.append(
                CandidateSource(
                    brand_id=brand_id,
                    brand_name=name,
                    industry_id=entry.get("suggested_industry_id") or "uncategorised",
                    search_tag=_S15_RESIDUAL_TAG,
                    weight=weight,
                    note=(
                        f"Global trending | llm_confidence={float(confidence):.2f} | "
                        f"{(entry.get('evidence') or '')[:200]}"
                    )[:380],
                    exa_query=query,
                    exa_result_url=str(entry.get("source_url") or "").strip() or None,
                )
            )
    return sources


async def run(
    *,
    talent_data: dict[str, Any],
    taxonomies: Any,
    brand_industry_map: dict[str, Any],
    talent_country: str | None = None,
    s15_global_enabled: bool = True,
) -> list[CandidateSource]:
    """Compose S15-residual + S16 + S17 into one flat CandidateSource list.

    S16 + S17 are gated by their existing settings flags
    (``enable_last30days_discovery`` + ``enable_search_17_paid_social``).
    S15-global can be disabled here via ``s15_global_enabled=False`` for
    cheap dev / test runs.
    """
    _ = taxonomies  # reserved for future use
    sources: list[CandidateSource] = []

    if s15_global_enabled:
        try:
            sources.extend(await _exa_global_funded(talent_country=talent_country))
        except Exception as exc:
            log.warning("phase_4_s15_global_failed", error=str(exc))

    # S16 — gated behind settings.enable_last30days_discovery.
    from app.config import settings

    if settings.enable_last30days_discovery:
        try:
            # S16 keys on the talent's top industries today; v0.2 may
            # rewire to use approved_industries. For now we pass an
            # empty list which makes S16 a no-op until the existing
            # module is rewritten.
            sources.extend(
                await search_16_last30days_trending.run(
                    top_industry_ids=[],
                    brand_industry_map=brand_industry_map,
                )
            )
        except Exception as exc:
            log.warning("phase_4_s16_failed", error=str(exc))

    if settings.enable_search_17_paid_social:
        try:
            sources.extend(
                await search_17_paid_social_signal.run(
                    top_industry_ids=[],
                    brand_industry_map=brand_industry_map,
                )
            )
        except Exception as exc:
            log.warning("phase_4_s17_failed", error=str(exc))

    _ = talent_data
    return sources
