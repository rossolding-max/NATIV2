"""M7.7 — Life-stage → industry derivation tests."""

from __future__ import annotations

from app.services.discovery._industry_from_life_stage import (
    derive_industries_from_life_stage,
)


def test_unit__life_stage__dominant_band_drives_industries() -> None:
    audience = {
        "age_bands": [
            {"band": "25-34", "share": 0.55},
            {"band": "35-44", "share": 0.30},
            {"band": "18-24", "share": 0.15},
        ]
    }
    out = derive_industries_from_life_stage(audience_demographics=audience)
    ids = {p.industry_id for p in out}
    # 25-34 band -> wellness / supplements / femtech / etc.
    assert "wellness" in ids
    assert "femtech" in ids
    # Every proposal sources to life_stage.
    assert all(p.source == "life_stage" for p in out)
    # Rationale names the band.
    assert all("25-34" in p.rationale for p in out)


def test_unit__life_stage__empty_when_no_age_bands() -> None:
    out = derive_industries_from_life_stage(audience_demographics={})
    assert out == []


def test_unit__life_stage__handles_pct_alias() -> None:
    """Some upstream feeds use ``pct`` instead of ``share``."""
    audience = {"age_bands": [{"band": "35-44", "pct": 0.80}]}
    out = derive_industries_from_life_stage(audience_demographics=audience)
    ids = {p.industry_id for p in out}
    assert "parenting-products" in ids


def test_unit__life_stage__band_not_in_map_returns_empty() -> None:
    """An age band outside the 6 known buckets returns []."""
    audience = {"age_bands": [{"band": "5-12", "share": 0.99}]}
    out = derive_industries_from_life_stage(audience_demographics=audience)
    assert out == []
