"""M7.4 — Discovered seed-map writeback (atomic append)."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.discovery._discovered_writer import append_discovered_brands


def _write_curated(path: Path, brands: list[dict]) -> None:  # type: ignore[type-arg]
    (path / "brand_industry_map.json").write_text(json.dumps({"version": 1, "brands": brands}))


def _write_discovered(path: Path, brands: list[dict]) -> None:  # type: ignore[type-arg]
    (path / "brand_industry_map_discovered.json").write_text(
        json.dumps({"version": 1, "brands": brands})
    )


def test_unit__discovered_writer__appends_net_new_brand(tmp_path: Path) -> None:
    _write_curated(tmp_path, [{"name": "Ford", "industry_id": "auto-oems"}])
    _write_discovered(tmp_path, [])
    payloads = [
        {"brand_id": "kudos", "brand": "Kudos", "industry_id": "diapers-nappies"},
    ]
    added = append_discovered_brands(payloads, data_dir=tmp_path, search_run_id="run_test_001")
    assert added == 1
    file = tmp_path / "brand_industry_map_discovered.json"
    discovered = json.loads(file.read_text())
    assert len(discovered["brands"]) == 1
    assert discovered["brands"][0]["brand_id"] == "kudos"
    assert discovered["brands"][0]["first_surfaced_in_run"] == "run_test_001"


def test_unit__discovered_writer__skips_brands_in_curated_seed(tmp_path: Path) -> None:
    """Don't double-write brands the curated file already has."""
    _write_curated(tmp_path, [{"name": "Ford", "industry_id": "auto-oems"}])
    _write_discovered(tmp_path, [])
    payloads = [
        # "Ford Motor Company" normalises to "ford" → matches curated "Ford".
        {
            "brand_id": "ford-motor-company",
            "brand": "Ford Motor Company",
            "industry_id": "auto-oems",
        },
    ]
    added = append_discovered_brands(payloads, data_dir=tmp_path)
    assert added == 0
    discovered = json.loads((tmp_path / "brand_industry_map_discovered.json").read_text())
    assert discovered["brands"] == []


def test_unit__discovered_writer__skips_brands_already_in_discovered(tmp_path: Path) -> None:
    """A second run that surfaces the same brand doesn't append a duplicate."""
    _write_curated(tmp_path, [])
    _write_discovered(
        tmp_path,
        [
            {
                "brand_id": "kudos",
                "name": "Kudos",
                "industry_id": "diapers-nappies",
                "discovered_at": "2026-05-29T00:00:00Z",
            }
        ],
    )
    payloads = [
        {"brand_id": "kudos", "brand": "Kudos", "industry_id": "diapers-nappies"},
    ]
    added = append_discovered_brands(payloads, data_dir=tmp_path)
    assert added == 0


def test_unit__discovered_writer__missing_discovered_file_creates_it(tmp_path: Path) -> None:
    _write_curated(tmp_path, [])
    # No discovered file initially.
    payloads = [{"brand_id": "kudos", "brand": "Kudos", "industry_id": "diapers-nappies"}]
    added = append_discovered_brands(payloads, data_dir=tmp_path)
    assert added == 1
    file = tmp_path / "brand_industry_map_discovered.json"
    assert file.exists()
    assert json.loads(file.read_text())["brands"][0]["name"] == "Kudos"


def test_unit__discovered_writer__skips_payloads_missing_required_fields(tmp_path: Path) -> None:
    _write_curated(tmp_path, [])
    _write_discovered(tmp_path, [])
    payloads = [
        {"brand_id": "no-name", "industry_id": "diapers-nappies"},  # no name
        {"brand": "No Industry", "brand_id": "no-industry"},  # no industry_id
        {"brand_id": "ok", "brand": "OK", "industry_id": "toys"},
    ]
    added = append_discovered_brands(payloads, data_dir=tmp_path)
    assert added == 1
    discovered = json.loads((tmp_path / "brand_industry_map_discovered.json").read_text())
    assert {b["brand_id"] for b in discovered["brands"]} == {"ok"}


def test_unit__discovered_writer__empty_payloads_no_op(tmp_path: Path) -> None:
    _write_curated(tmp_path, [])
    added = append_discovered_brands([], data_dir=tmp_path)
    assert added == 0
    # No file should be created when there's nothing to append.
    assert not (tmp_path / "brand_industry_map_discovered.json").exists()
