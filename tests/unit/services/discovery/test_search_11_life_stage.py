"""Search 11 (audience life-stage industry mapping)."""

from __future__ import annotations

from typing import Any

from app.services.discovery import search_11_life_stage


def _brand_map(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"brands": list(entries)}


def test_unit__search_11__dominant_band_emits_life_stage_industries() -> None:
    """Audience dominated by 25-34 -> wellness/supplements industries surface."""
    bim = _brand_map(
        {"name": "Athletic Greens", "industry_id": "supplements-brands"},
        {"name": "Notion", "industry_id": "saas"},  # not in life-stage map
    )
    sources = search_11_life_stage.run(
        audience_demographics={
            "age_bands": [
                {"band": "25-34", "share": 0.55},
                {"band": "18-24", "share": 0.25},
                {"band": "35-44", "share": 0.20},
            ]
        },
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    assert sources[0].brand_id == "athletic-greens"
    assert sources[0].search_tag == "life_stage_signal"
    assert sources[0].weight == 0.04


def test_unit__search_11__no_age_bands_returns_empty() -> None:
    sources = search_11_life_stage.run(
        audience_demographics={},
        brand_industry_map=_brand_map(
            {"name": "Anyone", "industry_id": "wellness"},
        ),
    )
    assert sources == []


def test_unit__search_11__unknown_band_returns_empty() -> None:
    sources = search_11_life_stage.run(
        audience_demographics={"age_bands": [{"band": "unknown", "share": 0.99}]},
        brand_industry_map=_brand_map({"name": "X", "industry_id": "wellness"}),
    )
    assert sources == []


def test_unit__search_11__multiple_bands_pick_highest_share() -> None:
    """45-54 leads -> financial-services / travel-hospitality industries surface, not 25-34's."""
    bim = _brand_map(
        {"name": "Wells Fargo", "industry_id": "financial-services"},
        {"name": "Athletic Greens", "industry_id": "supplements-brands"},  # 25-34
    )
    sources = search_11_life_stage.run(
        audience_demographics={
            "age_bands": [
                {"band": "25-34", "share": 0.30},
                {"band": "45-54", "share": 0.50},
                {"band": "55+", "share": 0.20},
            ]
        },
        brand_industry_map=bim,
    )
    # Only the 45-54 industries surface; supplements-brands (25-34's set) shouldn't.
    brand_ids = {s.brand_id for s in sources}
    assert "wells-fargo" in brand_ids
    assert "athletic-greens" not in brand_ids


def test_unit__search_11__industry_id_missing_skipped() -> None:
    bim = _brand_map({"name": "X"})  # no industry_id
    sources = search_11_life_stage.run(
        audience_demographics={"age_bands": [{"band": "25-34", "share": 1.0}]},
        brand_industry_map=bim,
    )
    assert sources == []
