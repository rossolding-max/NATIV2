"""M7.6 — Social-handle enrichment for Exa-discovered brands.

The LLM extractor in S15/S18 only captures social handles that appear
as visible text in the Exa result page. Most brand homepages embed
IG/TikTok icons in the footer; the handles themselves don't show up
in the scraped text. So the initial extraction misses ~95% of IG/TikTok
handles.

This module runs follow-up Exa queries (``<brand> instagram``,
``<brand> tiktok``) per brand that needs enrichment and extracts the
handle from the first matching URL in the results. Cheap, dumb, and
effective: instagram.com/X and tiktok.com/@X URLs are nearly always
on the brand's own social pages.
"""

from __future__ import annotations

import re
from typing import Any

from app.utils.logging import get_logger

log = get_logger(__name__)


# Match an Instagram handle from URLs like:
#   https://www.instagram.com/kudosdiapers
#   https://instagram.com/kudosdiapers/
_IG_URL_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?!p/|reel/|tv/|explore/|stories/)([A-Za-z0-9_.]{2,30})/?",
    re.IGNORECASE,
)
# TikTok handle URLs: https://www.tiktok.com/@username
_TIKTOK_URL_RE = re.compile(
    r"https?://(?:www\.)?tiktok\.com/@([A-Za-z0-9_.]{2,30})/?",
    re.IGNORECASE,
)


def _extract_first_match(text: str, pattern: re.Pattern[str]) -> str | None:
    m = pattern.search(text or "")
    if m:
        return m.group(1)
    return None


async def enrich_social_handles(
    *,
    brand_name: str,
    needs_instagram: bool,
    needs_tiktok: bool,
    exa_client: Any = None,
) -> dict[str, str | None]:
    """Run up-to-two follow-up Exa queries per brand to fill in missing IG/TikTok handles.

    Returns a dict shape ``{"instagram": str | None, "tiktok": str | None}``.
    Either field can be None when Exa returns no usable handle.

    ``exa_client`` is for test injection — production passes None and the
    function constructs one via ``ExaClient()``.
    """
    out: dict[str, str | None] = {"instagram": None, "tiktok": None}
    if not (needs_instagram or needs_tiktok):
        return out
    if not brand_name or not brand_name.strip():
        return out

    if exa_client is None:
        from app.vendors.exa import ExaClient

        exa_client = ExaClient()

    async def _query_first_match(q: str, pattern: re.Pattern[str]) -> str | None:
        try:
            resp = await exa_client.search(q, num_results=5)
        except Exception as exc:
            log.warning("social_enrichment_exa_failed", brand=brand_name, query=q, error=str(exc))
            return None
        results = resp.get("results") or []
        for r in results:
            if not isinstance(r, dict):
                continue
            for field_key in ("url", "title", "text"):
                value = r.get(field_key) or ""
                handle = _extract_first_match(str(value), pattern)
                if handle:
                    return handle
        return None

    if needs_instagram:
        ig = await _query_first_match(f"{brand_name} instagram", _IG_URL_RE)
        if ig:
            out["instagram"] = f"@{ig}"
    if needs_tiktok:
        tt = await _query_first_match(f"{brand_name} tiktok", _TIKTOK_URL_RE)
        if tt:
            out["tiktok"] = f"@{tt}"
    return out


def _seed_social(seed_brands: list[dict[str, Any]], normalized_name: str) -> dict[str, Any] | None:
    """Look up social_handles on a seed-map entry by normalized brand name."""
    from app.services.discovery._brand_normalizer import normalize_brand_name

    for entry in seed_brands:
        for value in (entry.get("name"), entry.get("brand_id")):
            if isinstance(value, str) and normalize_brand_name(value) == normalized_name:
                return entry.get("social_handles") or None
        for alias in entry.get("aliases") or []:
            if isinstance(alias, str) and normalize_brand_name(alias) == normalized_name:
                return entry.get("social_handles") or None
    return None


async def enrich_extracted_brands_inplace(
    extracted: list[dict[str, Any]],
    seed_brands: list[dict[str, Any]],
    *,
    exa_client: Any = None,
) -> None:
    """Mutate ``extracted`` so each entry's ``social_handles`` is filled in
    with Instagram + TikTok handles where the LLM extraction returned null
    AND the merged seed map doesn't already have them.

    Runs at most 2 Exa calls per unique brand. Skips brands already known
    in the seed map. Same handle is applied to every (brand, query) hit.
    """
    from app.services.discovery._brand_normalizer import normalize_brand_name

    if not extracted:
        return

    # Step 1: aggregate initial social_handles per unique brand.
    by_brand: dict[str, dict[str, str | None]] = {}
    for cand in extracted:
        name = (cand.get("brand_name") or "").strip()
        if not name:
            continue
        normalized = normalize_brand_name(name)
        if not normalized:
            continue
        merged = by_brand.setdefault(
            normalized,
            {
                "name": name,
                "instagram": None,
                "tiktok": None,
            },
        )
        social = cand.get("social_handles") or {}
        if isinstance(social, dict):
            for platform in ("instagram", "tiktok"):
                value = social.get(platform)
                if value and not merged.get(platform):
                    merged[platform] = value
        # Also consult the seed map (covers M7.5-discovered entries).
        seed_social = _seed_social(seed_brands, normalized)
        if seed_social:
            for platform in ("instagram", "tiktok"):
                value = seed_social.get(platform)
                if value and not merged.get(platform):
                    merged[platform] = value

    # Step 2: enrichment pass for brands missing handles.
    for merged in by_brand.values():
        needs_ig = not merged.get("instagram")
        needs_tt = not merged.get("tiktok")
        if not (needs_ig or needs_tt):
            continue
        handles = await enrich_social_handles(
            brand_name=str(merged["name"]),
            needs_instagram=needs_ig,
            needs_tiktok=needs_tt,
            exa_client=exa_client,
        )
        if handles.get("instagram") and not merged.get("instagram"):
            merged["instagram"] = handles["instagram"]
        if handles.get("tiktok") and not merged.get("tiktok"):
            merged["tiktok"] = handles["tiktok"]

    # Step 3: write the enriched handles back onto every (brand, query) hit.
    for cand in extracted:
        name = (cand.get("brand_name") or "").strip()
        normalized = normalize_brand_name(name) if name else ""
        merged = by_brand.get(normalized)
        if not merged:
            continue
        current = cand.get("social_handles") or {}
        if not isinstance(current, dict):
            current = {}
        for platform in ("instagram", "tiktok"):
            value = merged.get(platform)
            if value and not current.get(platform):
                current[platform] = value
        cand["social_handles"] = current or None
