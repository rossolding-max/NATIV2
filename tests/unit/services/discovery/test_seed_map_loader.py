"""M7.4 — Seed-map loader merges curated + discovered files."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.discovery._seed_map_loader import load_merged_brand_industry_map


def _write_curated(path: Path, brands: list[dict]) -> None:  # type: ignore[type-arg]
    payload = {"version": 1, "updated": "2026-05-29", "brands": brands}
    (path / "brand_industry_map.json").write_text(json.dumps(payload))


def _write_discovered(path: Path, brands: list[dict]) -> None:  # type: ignore[type-arg]
    payload = {"version": 1, "updated": "2026-05-29", "brands": brands}
    (path / "brand_industry_map_discovered.json").write_text(json.dumps(payload))


def test_unit__seed_loader__merges_curated_and_discovered(tmp_path: Path) -> None:
    _write_curated(tmp_path, [{"brand_id": "ford", "name": "Ford", "industry_id": "auto-oems"}])
    _write_discovered(
        tmp_path, [{"brand_id": "kudos", "name": "Kudos", "industry_id": "diapers-nappies"}]
    )
    merged = load_merged_brand_industry_map(tmp_path)
    ids = {b["brand_id"] for b in merged["brands"]}
    assert ids == {"ford", "kudos"}


def test_unit__seed_loader__curated_wins_on_conflict(tmp_path: Path) -> None:
    """If a brand_id exists in both files, the curated entry wins (rich attrs)."""
    _write_curated(
        tmp_path,
        [
            {
                "brand_id": "ford",
                "name": "Ford",
                "industry_id": "auto-oems",
                "sells_in_countries": "global",
                "hq_country": "US",
            }
        ],
    )
    _write_discovered(
        tmp_path, [{"brand_id": "ford", "name": "Ford Motor Company", "industry_id": "auto-oems"}]
    )
    merged = load_merged_brand_industry_map(tmp_path)
    ford = next(b for b in merged["brands"] if b["brand_id"] == "ford")
    # Curated wins.
    assert ford["name"] == "Ford"
    assert ford.get("sells_in_countries") == "global"


def test_unit__seed_loader__missing_discovered_file_loads_curated_only(tmp_path: Path) -> None:
    _write_curated(tmp_path, [{"brand_id": "ford", "name": "Ford", "industry_id": "auto-oems"}])
    # No discovered file present.
    merged = load_merged_brand_industry_map(tmp_path)
    assert len(merged["brands"]) == 1
    assert merged["brands"][0]["brand_id"] == "ford"


def test_unit__seed_loader__missing_curated_returns_discovered_only(tmp_path: Path) -> None:
    _write_discovered(tmp_path, [{"brand_id": "kudos", "name": "Kudos"}])
    merged = load_merged_brand_industry_map(tmp_path)
    assert len(merged["brands"]) == 1
    assert merged["brands"][0]["brand_id"] == "kudos"
