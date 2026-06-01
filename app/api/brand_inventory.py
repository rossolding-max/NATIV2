"""M7.7+ — Global brand-inventory introspection endpoint.

GET /api/v1/brand-inventory/summary

Returns counts over the merged seed map (curated baseline +
auto-grown discovered file). Lets the operator see how the central
brand inventory is growing across talents — total, by industry, by
sub-industry, by category, by source.

The discovered file is appended to atomically at the end of every
brand-discovery run (see ``_discovered_writer.py``). This endpoint
just reads the merged result; no writes.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.responses import APIResponse, make_meta
from app.services.discovery._seed_map_loader import load_merged_brand_industry_map

router = APIRouter(prefix="/brand-inventory", tags=["brand-inventory"])


def _summarise(brands: list[Any]) -> dict[str, Any]:
    by_industry: dict[str, int] = {}
    by_sub: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_source: dict[str, int] = {}
    with_domain = 0
    with_social = 0

    for entry in brands:
        if not isinstance(entry, dict):
            continue
        iid = entry.get("industry_id")
        if isinstance(iid, str) and iid:
            by_industry[iid] = by_industry.get(iid, 0) + 1
        sub = entry.get("sub_industry_id")
        if isinstance(sub, str) and sub:
            by_sub[sub] = by_sub.get(sub, 0) + 1
        cat = entry.get("brand_category") or "uncategorised"
        if isinstance(cat, str):
            by_category[cat] = by_category.get(cat, 0) + 1
        src = entry.get("source") or "curated"
        if isinstance(src, str):
            by_source[src] = by_source.get(src, 0) + 1
        if entry.get("domain"):
            with_domain += 1
        if entry.get("social_handles"):
            with_social += 1

    return {
        "by_industry": dict(sorted(by_industry.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_sub_industry": dict(sorted(by_sub.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_brand_category": dict(sorted(by_category.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_source": dict(sorted(by_source.items(), key=lambda kv: (-kv[1], kv[0]))),
        "with_domain": with_domain,
        "with_social_handles": with_social,
    }


@router.get("/summary", response_model=APIResponse[dict[str, Any]])
def get_inventory_summary() -> APIResponse[dict[str, Any]]:
    """Return a snapshot of the global brand inventory.

    Counts come from the merged seed map (curated + discovered). Industry
    distribution is sorted by count desc, then by id asc for stable
    ordering across calls.
    """
    payload = load_merged_brand_industry_map()
    brands = payload.get("brands") or []
    summary = _summarise(brands)
    summary["total_brands"] = len(brands)
    summary["updated_curated"] = payload.get("updated_curated")
    summary["updated_discovered"] = payload.get("updated_discovered")
    return APIResponse[dict[str, Any]](data=summary, meta=make_meta(), errors=[])
