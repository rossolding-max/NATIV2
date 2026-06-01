"""Geographic filter (M7.3) — talent country extraction + brand pass/fail rules.

The shared utility this exercises lives at
``app/services/discovery/_geographic_filter.py``.
"""

from __future__ import annotations

from app.services.discovery._geographic_filter import (
    brand_passes_geo,
    extract_talent_countries,
    filter_sources_by_geo,
)
from app.services.discovery._models import CandidateSource

# ── extract_talent_countries ────────────────────────────────────────


def test_unit__geo__extract_from_audience_top_countries_strings() -> None:
    """Audience demographics with string country codes."""
    talent_data = {"audience_demographics": {"top_countries": ["us", "GB", "  CA  "]}}
    assert extract_talent_countries(talent_data) == ["US", "GB", "CA"]


def test_unit__geo__extract_from_audience_top_countries_dicts() -> None:
    """Audience demographics with dict entries (production shape with share)."""
    talent_data = {
        "audience_demographics": {
            "top_countries": [
                {"country_code": "US", "share": 0.72},
                {"country": "GB", "share": 0.10},
                {"code": "AU", "share": 0.05},
                {"iso2": "ca", "share": 0.04},
            ]
        }
    }
    assert extract_talent_countries(talent_data) == ["GB", "AU", "CA"]


def test_unit__geo__fallback_to_location_country_when_audience_empty() -> None:
    """When audience.top_countries is absent, fall back to location.country."""
    talent_data = {"location": {"country": "us"}}
    assert extract_talent_countries(talent_data) == ["US"]


def test_unit__geo__empty_when_both_missing() -> None:
    """Both audience and location missing -> empty (filter bypass case)."""
    assert extract_talent_countries({}) == []


# ── brand_passes_geo ────────────────────────────────────────────────


def test_unit__geo__brand_passes_when_no_talent_countries() -> None:
    """Empty talent country list bypasses the filter."""
    brand = {"sells_in_countries": ["GB"]}
    assert brand_passes_geo(brand, []) is True


def test_unit__geo__brand_passes_when_sells_in_missing() -> None:
    """Missing field -> assume global (soft floor)."""
    brand = {"name": "Some Brand"}
    assert brand_passes_geo(brand, ["US"]) is True


def test_unit__geo__brand_passes_with_string_global() -> None:
    """sells_in_countries == 'global' -> always passes."""
    brand = {"sells_in_countries": "global"}
    assert brand_passes_geo(brand, ["US"]) is True


def test_unit__geo__brand_passes_with_list_intersecting() -> None:
    """List containing one of the talent's countries -> passes."""
    brand = {"sells_in_countries": ["US", "GB", "CA"]}
    assert brand_passes_geo(brand, ["US"]) is True


def test_unit__geo__brand_fails_with_explicit_non_matching_list() -> None:
    """The Tesco case: sells_in=['GB','IE'] talent in US -> drop."""
    brand = {"sells_in_countries": ["GB", "IE"]}
    assert brand_passes_geo(brand, ["US"]) is False


def test_unit__geo__brand_passes_with_empty_list_treated_as_global() -> None:
    """An empty list is data-tag-present-but-unfilled; treat as global."""
    brand = {"sells_in_countries": []}
    assert brand_passes_geo(brand, ["US"]) is True


def test_unit__geo__brand_passes_with_global_inside_list() -> None:
    """List containing 'GLOBAL' (case-insensitive) -> passes."""
    brand = {"sells_in_countries": ["global"]}
    assert brand_passes_geo(brand, ["US"]) is True


def test_unit__geo__brand_passes_with_unknown_shape() -> None:
    """A non-string non-list value -> assume global (defensive default)."""
    brand = {"sells_in_countries": 12345}
    assert brand_passes_geo(brand, ["US"]) is True


# ── filter_sources_by_geo ──────────────────────────────────────────


def test_unit__geo__filter_drops_uk_only_for_us_talent() -> None:
    """Tesco fails; Whole Foods + Aldi + missing-geo brand pass."""
    brand_index = {
        "tesco": {"name": "Tesco", "sells_in_countries": ["GB", "IE"]},
        "sainsbury's": {"name": "Sainsbury's", "sells_in_countries": ["GB"]},
        "whole foods": {"name": "Whole Foods", "sells_in_countries": ["US", "GB", "CA"]},
        "aldi": {"name": "Aldi", "sells_in_countries": "global"},
        "missing geo brand": {"name": "Missing Geo Brand"},
    }
    sources = [
        CandidateSource(
            brand_id="tesco",
            brand_name="Tesco",
            industry_id="grocery",
            search_tag="primary_industry",
            weight=0.30,
        ),
        CandidateSource(
            brand_id="sainsburys",
            brand_name="Sainsbury's",
            industry_id="grocery",
            search_tag="primary_industry",
            weight=0.30,
        ),
        CandidateSource(
            brand_id="whole-foods",
            brand_name="Whole Foods",
            industry_id="grocery",
            search_tag="primary_industry",
            weight=0.30,
        ),
        CandidateSource(
            brand_id="aldi",
            brand_name="Aldi",
            industry_id="grocery",
            search_tag="primary_industry",
            weight=0.30,
        ),
        CandidateSource(
            brand_id="missing",
            brand_name="Missing Geo Brand",
            industry_id="grocery",
            search_tag="primary_industry",
            weight=0.30,
        ),
    ]
    kept = filter_sources_by_geo(sources, brand_index, ["US"])
    kept_names = {s.brand_name for s in kept}
    assert kept_names == {"Whole Foods", "Aldi", "Missing Geo Brand"}


def test_unit__geo__filter_passes_unknown_brand_through() -> None:
    """Sources for net-new (Exa-discovered) brands NOT in the seed index
    bypass the geo check — they're tier=emerging anyway and we have no
    geo data to apply."""
    sources = [
        CandidateSource(
            brand_id="newbrand",
            brand_name="Net-New Brand",
            industry_id="toys",
            search_tag="recently_funded",
            weight=0.20,
        )
    ]
    kept = filter_sources_by_geo(sources, brand_index={}, talent_countries=["US"])
    assert len(kept) == 1
    assert kept[0].brand_name == "Net-New Brand"


def test_unit__geo__filter_no_op_when_talent_countries_empty() -> None:
    """No talent geo signal -> no-op (preserves v0.1 behaviour for Kevin)."""
    sources = [
        CandidateSource(
            brand_id="tesco",
            brand_name="Tesco",
            industry_id="grocery",
            search_tag="primary_industry",
            weight=0.30,
        )
    ]
    brand_index = {"tesco": {"name": "Tesco", "sells_in_countries": ["GB"]}}
    kept = filter_sources_by_geo(sources, brand_index, talent_countries=[])
    assert kept == sources
