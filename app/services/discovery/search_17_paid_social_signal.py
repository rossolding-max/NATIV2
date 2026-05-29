"""Search 17 — brands spending heavily on paid social media advertising.

For each of the talent's top industries, query Meta Ad Library + TikTok
Creative Center for active ads in the last 30 days. Brands appearing on
either platform with at least ``settings.paid_social_min_active_ads``
active creatives surface as candidates. Multi-platform brands get a
higher weight (stronger commercial-intent signal).

v1 (M7.2): count-based signal — number of active ads in last 30 days.
v2 (deferred per V2-DISCOVERY-02): swap to estimated-spend $ values via
Pathmatics / SensorTower / AdBeat.

Cost guards:
- ``settings.paid_social_max_industries_per_run`` caps fan-out across
  industries (default 3).
- Both vendor clients have their own rate-limit budgets
  (Meta 200/hr, TikTok 20/min) checked at the request layer.
- No LLM calls in v1 — brand-name normalisation is direct lowercase
  comparison against ``brand_industry_map.brands[].name + aliases``.
  Add LLM normalisation in M7.2.1 if name-mismatch noise proves real.
"""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.services.discovery._models import CandidateSource
from app.utils.logging import get_logger

log = get_logger(__name__)


SINGLE_PLATFORM_TAG = "paid_social_active"
MULTI_PLATFORM_TAG = "paid_social_active_multi"
SINGLE_PLATFORM_WEIGHT = 0.20
MULTI_PLATFORM_WEIGHT = 0.30


def _slugify(name: str) -> str:
    import re

    cleaned = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return cleaned or "unknown"


def _industry_keywords(industry_id: str) -> str:
    """Convert ``activewear-performance`` -> ``"activewear performance"`` for Meta search."""
    return industry_id.replace("-", " ").replace("_", " ").strip()


def _existing_brand_index(brand_industry_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build a lower-case name + alias -> brand-dict lookup.

    Used to normalise vendor-returned page/brand names against the seed
    map. A brand returned by Meta with ``page_name="ALO Yoga - Official"``
    matches a seed-map entry with ``aliases=["alo", "alo yoga"]``.
    """
    index: dict[str, dict[str, Any]] = {}
    for entry in brand_industry_map.get("brands") or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if isinstance(name, str):
            index[name.strip().lower()] = entry
        for alias in entry.get("aliases") or []:
            if isinstance(alias, str):
                index[alias.strip().lower()] = entry
    return index


def _match_existing_brand(
    vendor_name: str, brand_index: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """Best-effort name match against the existing seed map.

    v1 = lowercase exact match on full name OR any alias. Naive but
    cheap and zero LLM cost. Misses are surfaced as net-new brands
    with vendor-derived names and slugified ids.
    """
    cleaned = vendor_name.strip().lower()
    if cleaned in brand_index:
        return brand_index[cleaned]
    # Try stripping common page-name suffixes Meta adds.
    for suffix in (" - official", " official", " inc", " ltd", " llc", " co"):
        if cleaned.endswith(suffix):
            stripped = cleaned[: -len(suffix)].strip()
            if stripped in brand_index:
                return brand_index[stripped]
    return None


async def _query_meta(
    *,
    industry_id: str,
    countries: list[str],
    min_active_ads: int,
) -> dict[str, dict[str, Any]]:
    """Query Meta Ad Library for one industry. Returns ``{brand_name -> {ad_count, ...}}``.

    Filters to brands with >= ``min_active_ads`` to drop noise.
    """
    from app.vendors.meta_ads import MetaAdsClient

    try:
        meta = MetaAdsClient()
    except Exception as exc:
        log.warning(
            "search_17_meta_client_init_failed",
            industry=industry_id,
            error=str(exc),
        )
        return {}

    keywords = _industry_keywords(industry_id)
    try:
        per_brand = await meta.count_active_ads_per_advertiser(
            search_terms=keywords,
            countries=countries,
            days_back=30,
        )
    except Exception as exc:
        log.warning(
            "search_17_meta_search_failed",
            industry=industry_id,
            error=str(exc),
        )
        return {}

    return {
        name: data for name, data in per_brand.items() if data.get("ad_count", 0) >= min_active_ads
    }


async def _query_tiktok(
    *,
    industry_ids: list[str],
    region: str,
    min_active_ads: int,
) -> dict[str, dict[str, Any]]:
    """Query TikTok Creative Center across all top industries.

    TikTok takes a single request per industry, returns the top advertisers.
    We merge across industries and filter by ``min_active_ads``.
    """
    from app.vendors.tiktok_creative_center import TikTokCreativeCenterClient

    try:
        tiktok = TikTokCreativeCenterClient()
    except Exception as exc:
        log.warning("search_17_tiktok_client_init_failed", error=str(exc))
        return {}

    try:
        per_brand = await tiktok.count_active_advertisers_per_industry(
            industries=industry_ids,
            region=region,
        )
    except Exception as exc:
        log.warning("search_17_tiktok_search_failed", error=str(exc))
        return {}

    return {
        name: data for name, data in per_brand.items() if data.get("ad_count", 0) >= min_active_ads
    }


async def run(
    *,
    top_industry_ids: list[str],
    brand_industry_map: dict[str, Any],
    max_industries: int | None = None,
    min_active_ads: int | None = None,
) -> list[CandidateSource]:
    """Run Search 17 across the top-N industries.

    Returns ``CandidateSource`` records. Multi-platform brands get
    ``paid_social_active_multi`` with weight 0.30; single-platform brands
    get ``paid_social_active`` with weight 0.20.
    """
    if not top_industry_ids:
        return []
    if not settings.enable_search_17_paid_social:
        log.info("search_17_skipped_gate_off")
        return []

    cap = max_industries or settings.paid_social_max_industries_per_run
    threshold = min_active_ads or settings.paid_social_min_active_ads
    industries = list(dict.fromkeys(top_industry_ids))[:cap]
    countries = list(settings.meta_ads_default_countries)

    brand_index = _existing_brand_index(brand_industry_map)

    # Aggregate Meta hits per brand across industries.
    meta_per_brand: dict[str, dict[str, Any]] = {}
    for industry_id in industries:
        per_brand = await _query_meta(
            industry_id=industry_id,
            countries=countries,
            min_active_ads=threshold,
        )
        for name, data in per_brand.items():
            entry = meta_per_brand.setdefault(
                name,
                {
                    "ad_count": 0,
                    "industries": [],
                    "page_id": data.get("page_id"),
                },
            )
            entry["ad_count"] += data.get("ad_count", 0)
            if industry_id not in entry["industries"]:
                entry["industries"].append(industry_id)

    tiktok_per_brand = await _query_tiktok(
        industry_ids=industries,
        region=countries[0] if countries else "US",
        min_active_ads=threshold,
    )

    # Merge by lower-case brand name. A brand appearing on BOTH platforms
    # gets the multi-platform tag + higher weight.
    sources: list[CandidateSource] = []
    seen_lower: set[str] = set()

    def _emit(
        canonical_name: str,
        first_industry: str,
        tag: str,
        weight: float,
        note: str,
    ) -> None:
        existing = _match_existing_brand(canonical_name, brand_index)
        if existing is not None:
            brand_id = (
                existing.get("id")
                or existing.get("brand_id")
                or _slugify(existing.get("name") or canonical_name)
            )
            display_name = existing.get("name") or canonical_name
            industry_id = (
                (existing.get("industry_ids") or [None])[0]
                or existing.get("industry_id")
                or first_industry
            )
        else:
            brand_id = _slugify(canonical_name)
            display_name = canonical_name
            industry_id = first_industry
        sources.append(
            CandidateSource(
                brand_id=brand_id,
                brand_name=display_name,
                industry_id=industry_id,
                search_tag=tag,
                weight=weight,
                note=note,
            )
        )
        seen_lower.add(canonical_name.strip().lower())

    # Multi-platform first — any brand in both maps.
    for meta_name, meta_data in meta_per_brand.items():
        for tt_name, tt_data in tiktok_per_brand.items():
            if meta_name.strip().lower() == tt_name.strip().lower():
                first_industry = (
                    meta_data["industries"][0] if meta_data.get("industries") else industries[0]
                )
                _emit(
                    meta_name,
                    first_industry,
                    MULTI_PLATFORM_TAG,
                    MULTI_PLATFORM_WEIGHT,
                    f"meta_active_ads={meta_data['ad_count']}; "
                    f"tiktok_active_creatives={tt_data['ad_count']}",
                )
                break

    # Single-platform Meta brands not already emitted.
    for name, data in meta_per_brand.items():
        if name.strip().lower() in seen_lower:
            continue
        first_industry = data["industries"][0] if data.get("industries") else industries[0]
        _emit(
            name,
            first_industry,
            SINGLE_PLATFORM_TAG,
            SINGLE_PLATFORM_WEIGHT,
            f"meta_active_ads={data['ad_count']}",
        )

    # Single-platform TikTok brands not already emitted.
    for name, data in tiktok_per_brand.items():
        if name.strip().lower() in seen_lower:
            continue
        first_industry = data["industries"][0] if data.get("industries") else industries[0]
        _emit(
            name,
            first_industry,
            SINGLE_PLATFORM_TAG,
            SINGLE_PLATFORM_WEIGHT,
            f"tiktok_active_creatives={data['ad_count']}",
        )

    log.info(
        "search_17_complete",
        candidates=len(sources),
        industries=industries,
        threshold=threshold,
    )
    return sources
