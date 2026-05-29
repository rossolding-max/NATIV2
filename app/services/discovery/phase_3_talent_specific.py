"""M7.7 Phase 3 — Talent-specific maintenance searches.

Wraps the four searches that depend on talent-specific lists (past brands,
similar talent's brands, values) and fires on EVERY discovery run (both
maintenance and full_build modes):

  - S1 — Re-engagement (existing module unchanged)
  - S2 — Similar talent brands (existing module unchanged)
  - S3 — Exa competitors of own past brands
  - S4 — Exa competitors of similar-talent's past brands
  - S13 — Values-aligned Exa (opt-in)

S3/S4 are Exa-based (M7.7 v2) — they replace the curated
brand_competitors.json lookup that only covered ~290 brands.
"""

from __future__ import annotations

from typing import Any

from app.services.discovery import (
    search_1_reengagement,
    search_2_similar_talent_brands,
)
from app.services.discovery._brand_normalizer import find_canonical_seed_entry
from app.services.discovery._competitor_search_exa import find_competitors
from app.services.discovery._models import CandidateSource
from app.services.discovery._values_search import find_values_aligned_brands
from app.utils.logging import get_logger
from app.utils.slugify import slugify_brand_name

log = get_logger(__name__)


_COMPETITOR_OF_PREVIOUS_TAG = "competitor_of_previous"
_COMPETITOR_OF_SIMILAR_TAG = "competitor_of_similar_talent"
_VALUES_ALIGNED_TAG = "values_aligned_exa"

# Weights mirror M7.6 — competitors of own brands score higher than
# competitors of similar talent's brands.
_S3_WEIGHT: float = 0.25
_S4_WEIGHT: float = 0.10
_VALUES_BASE_WEIGHT: float = 0.20
_VALUES_MAX_WEIGHT: float = 0.30


def _build_source_for_competitor(
    *,
    cand: dict[str, Any],
    source_brand_name: str,
    seed_brands: list[dict[str, Any]],
    fallback_industry_id: str,
    search_tag: str,
    weight: float,
) -> CandidateSource | None:
    name = (cand.get("brand_name") or "").strip()
    if not name:
        return None
    canonical = find_canonical_seed_entry(name, seed_brands)
    if canonical is not None:
        canonical_name = canonical.get("name") or name
        brand_id = slugify_brand_name(canonical_name)
        emit_name = canonical_name
        emit_industry = canonical.get("industry_id") or fallback_industry_id
        note_prefix = f"canonicalised from {name!r} | "
    else:
        brand_id = slugify_brand_name(name)
        emit_name = name
        emit_industry = fallback_industry_id
        note_prefix = ""
    if brand_id == "unknown":
        return None
    confidence = float(cand.get("confidence") or 0.0)
    evidence = (cand.get("evidence") or "")[:200]
    note = (
        f"{note_prefix}competitor of {source_brand_name!r} | "
        f"llm_confidence={confidence:.2f} | {evidence}"
    ).rstrip(" |")[:380]
    return CandidateSource(
        brand_id=brand_id,
        brand_name=emit_name,
        industry_id=emit_industry,
        search_tag=search_tag,
        weight=weight,
        note=note,
        exa_query=cand.get("exa_query"),
        exa_result_url=cand.get("source_url"),
    )


async def _exa_competitors_for_previous(
    *,
    previous_brands: list[dict[str, Any]],
    brand_industry_map: dict[str, Any],
    talent_country: str | None,
) -> list[CandidateSource]:
    if not previous_brands:
        return []
    seed_brands = [e for e in (brand_industry_map.get("brands") or []) if isinstance(e, dict)]
    sources: list[CandidateSource] = []
    seen: set[str] = set()
    for prev in previous_brands:
        if not prev:
            continue
        name = (prev.get("brand") or prev.get("name") or "").strip()
        if not name:
            continue
        fallback_industry_id = prev.get("industry_id") or "uncategorised"
        try:
            extracted = await find_competitors(brand_name=name, talent_country=talent_country)
        except Exception as exc:
            log.warning("phase_3_s3_failed", brand=name, error=str(exc))
            continue
        for cand in extracted:
            src = _build_source_for_competitor(
                cand=cand,
                source_brand_name=name,
                seed_brands=seed_brands,
                fallback_industry_id=fallback_industry_id,
                search_tag=_COMPETITOR_OF_PREVIOUS_TAG,
                weight=_S3_WEIGHT,
            )
            if src is None:
                continue
            dedup_key = f"{src.brand_id}:{src.exa_query}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            sources.append(src)
    return sources


async def _exa_competitors_for_similar(
    *,
    similar_talent: list[dict[str, Any]],
    brand_industry_map: dict[str, Any],
    talent_country: str | None,
) -> list[CandidateSource]:
    if not similar_talent:
        return []
    seed_brands = [e for e in (brand_industry_map.get("brands") or []) if isinstance(e, dict)]
    # Flatten the previous_brands list across similar talents, deduping by brand name.
    flat: list[tuple[str, str, str]] = []  # (brand_name, industry_id, similar_talent_id)
    seen_brands: set[str] = set()
    for entry in similar_talent:
        if not entry:
            continue
        sim_id = entry.get("talent_id") or entry.get("id") or "unknown"
        for pb in entry.get("previous_brands") or []:
            if not pb:
                continue
            name = (pb.get("brand") or pb.get("name") or "").strip()
            if not name or name.lower() in seen_brands:
                continue
            seen_brands.add(name.lower())
            industry_id = pb.get("industry_id") or "uncategorised"
            flat.append((name, str(industry_id), str(sim_id)))

    sources: list[CandidateSource] = []
    seen_emit: set[str] = set()
    for name, industry_id, _sim_id in flat:
        try:
            extracted = await find_competitors(brand_name=name, talent_country=talent_country)
        except Exception as exc:
            log.warning("phase_3_s4_failed", brand=name, error=str(exc))
            continue
        for cand in extracted:
            src = _build_source_for_competitor(
                cand=cand,
                source_brand_name=name,
                seed_brands=seed_brands,
                fallback_industry_id=industry_id,
                search_tag=_COMPETITOR_OF_SIMILAR_TAG,
                weight=_S4_WEIGHT,
            )
            if src is None:
                continue
            dedup_key = f"{src.brand_id}:{src.exa_query}"
            if dedup_key in seen_emit:
                continue
            seen_emit.add(dedup_key)
            sources.append(src)
    return sources


async def _exa_values_aligned(
    *,
    brand_preferences: dict[str, Any],
    approved_industries: list[str],
    brand_industry_map: dict[str, Any],
    talent_country: str | None,
) -> list[CandidateSource]:
    themes = brand_preferences.get("values_aligned_themes") or []
    if not isinstance(themes, list):
        return []
    theme_strings = [t for t in themes if isinstance(t, str)]
    if not theme_strings or not approved_industries:
        return []
    seed_brands = [e for e in (brand_industry_map.get("brands") or []) if isinstance(e, dict)]
    extracted = await find_values_aligned_brands(
        themes=theme_strings,
        industries=approved_industries,
        talent_country=talent_country,
    )
    sources: list[CandidateSource] = []
    seen: set[str] = set()
    for cand in extracted:
        name = (cand.get("brand_name") or "").strip()
        if not name:
            continue
        canonical = find_canonical_seed_entry(name, seed_brands)
        if canonical is not None:
            canonical_name = canonical.get("name") or name
            brand_id = slugify_brand_name(canonical_name)
            emit_name = canonical_name
            emit_industry = canonical.get("industry_id") or cand["industry_id"]
            note_prefix = f"canonicalised from {name!r} | "
        else:
            brand_id = slugify_brand_name(name)
            emit_name = name
            emit_industry = cand["industry_id"]
            note_prefix = ""
        dedup_key = f"{brand_id}:{cand.get('exa_query', '')}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        confidence = cand["confidence"]
        weight = (
            _VALUES_BASE_WEIGHT
            + (_VALUES_MAX_WEIGHT - _VALUES_BASE_WEIGHT) * (confidence - 0.70) / 0.30
        )
        weight = max(_VALUES_BASE_WEIGHT, min(_VALUES_MAX_WEIGHT, weight))
        themes_matched = cand.get("themes_matched") or []
        evidence = (cand.get("evidence") or "")[:200]
        note = (
            f"{note_prefix}values_themes={themes_matched} | "
            f"llm_confidence={confidence:.2f} | {evidence}"
        ).rstrip(" |")[:380]
        sources.append(
            CandidateSource(
                brand_id=brand_id,
                brand_name=emit_name,
                industry_id=emit_industry,
                search_tag=_VALUES_ALIGNED_TAG,
                weight=weight,
                note=note,
                exa_query=cand.get("exa_query"),
                exa_result_url=cand.get("source_url"),
            )
        )
    return sources


async def run(
    *,
    talent_data: dict[str, Any],
    brand_deals: list[Any],
    brand_industry_map: dict[str, Any],
    talent_country: str | None = None,
    approved_industries: list[str] | None = None,
    values_search_enabled: bool = False,
    today: Any = None,
) -> list[CandidateSource]:
    """Compose all Phase 3 searches into one flat CandidateSource list.

    S1 + S2 reuse the existing modules unchanged. S3 + S4 use Exa-based
    competitor search. S13 fires only when ``values_search_enabled`` is
    True AND the talent has ``values_aligned_themes``.

    ``approved_industries`` is required for S13 (values search keys on
    industries). When unset, S13 is silently skipped.
    """
    previous_brands = list(talent_data.get("previous_brands") or [])
    similar_talent = list(talent_data.get("similar_talent") or [])
    brand_preferences = dict(talent_data.get("brand_preferences") or {})

    sources: list[CandidateSource] = []

    # S1 — re-engagement.
    try:
        sources.extend(search_1_reengagement.run(brand_deals=brand_deals, today=today))
    except Exception as exc:
        log.warning("phase_3_s1_failed", error=str(exc))

    # S2 — similar-talent brands.
    try:
        sources.extend(
            search_2_similar_talent_brands.run(
                similar_talent=similar_talent, brand_industry_map=brand_industry_map
            )
        )
    except Exception as exc:
        log.warning("phase_3_s2_failed", error=str(exc))

    # S3 — Exa competitors of own past brands.
    sources.extend(
        await _exa_competitors_for_previous(
            previous_brands=previous_brands,
            brand_industry_map=brand_industry_map,
            talent_country=talent_country,
        )
    )

    # S4 — Exa competitors of similar-talent's past brands.
    sources.extend(
        await _exa_competitors_for_similar(
            similar_talent=similar_talent,
            brand_industry_map=brand_industry_map,
            talent_country=talent_country,
        )
    )

    # S13 — values-aligned Exa (opt-in).
    if values_search_enabled and approved_industries:
        sources.extend(
            await _exa_values_aligned(
                brand_preferences=brand_preferences,
                approved_industries=approved_industries,
                brand_industry_map=brand_industry_map,
                talent_country=talent_country,
            )
        )

    return sources
