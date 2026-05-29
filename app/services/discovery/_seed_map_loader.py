"""M7.4 — Merged brand seed-map loader.

Loads two files at orchestrator startup:

1. ``data/brand_industry_map.json`` — the curated baseline (290 brands
   with rich attributes: sells_in_countries, hq_country, social_handles,
   creator_program_presence, etc.).
2. ``data/brand_industry_map_discovered.json`` — the auto-grown sibling
   appended to at the end of every discovery run. Holds Exa-discovered
   and other net-new brands surfaced by previous runs across the agency.

Curated entries always win on ``brand_id`` conflict — a brand the agency
has hand-enriched takes precedence over the discovered stub even if the
discovered entry has newer ``updated_at`` data. This preserves
hand-curated attribute richness.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.discovery._brand_normalizer import normalize_brand_name
from app.utils.logging import get_logger

log = get_logger(__name__)


CURATED_FILENAME = "brand_industry_map.json"
DISCOVERED_FILENAME = "brand_industry_map_discovered.json"
# Legacy aliases — keep until callers are migrated.
_CURATED_FILENAME = CURATED_FILENAME
_DISCOVERED_FILENAME = DISCOVERED_FILENAME


def _load_one(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"brands": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _dedup_key(entry: dict[str, Any]) -> str:
    """Normalise a brand entry to a dedup key.

    Curated entries don't carry ``brand_id`` (derived from ``name`` via
    slugify elsewhere); discovered entries DO carry both. We pass the
    name through the brand normalizer so "Ford" (curated) and "Ford
    Motor Company" (discovered) share a key and curated wins.
    """
    name = entry.get("name") or entry.get("brand_id") or ""
    return normalize_brand_name(name)


def load_merged_brand_industry_map(data_dir: Path | None = None) -> dict[str, Any]:
    """Return a dict mirroring ``brand_industry_map.json`` shape, merged.

    Result keys: ``version`` (from curated), ``brands`` (list — curated
    entries appear first; discovered entries with the same lowercase
    name are dropped so the rich curated record wins).
    """
    repo_root = Path(__file__).resolve().parents[3]
    base = data_dir or repo_root / "data"
    curated = _load_one(base / _CURATED_FILENAME)
    discovered = _load_one(base / _DISCOVERED_FILENAME)

    curated_brands = curated.get("brands") or []
    discovered_brands = discovered.get("brands") or []

    merged_brands: list[dict[str, Any]] = list(curated_brands)
    curated_keys = {_dedup_key(b) for b in curated_brands if _dedup_key(b)}
    for entry in discovered_brands:
        key = _dedup_key(entry)
        if key and key not in curated_keys:
            merged_brands.append(entry)

    log.debug(
        "seed_map_merged",
        curated=len(curated_brands),
        discovered=len(discovered_brands),
        merged=len(merged_brands),
    )

    return {
        "version": curated.get("version", 1),
        "updated_curated": curated.get("updated"),
        "updated_discovered": discovered.get("updated"),
        "brands": merged_brands,
    }
