"""M7.7+ — Tests for the central brand_category resolver."""

from __future__ import annotations

from app.services.discovery._brand_category import (
    CATEGORY_BY_TAG,
    infer_brand_category,
)

# ── tag-driven inference ──────────────────────────────────────────


def test_unit__category__phase_2_tags_map_to_themselves() -> None:
    assert CATEGORY_BY_TAG["exa_emerging"] == "emerging"
    assert CATEGORY_BY_TAG["exa_growth"] == "growth"
    assert CATEGORY_BY_TAG["exa_established"] == "established"


def test_unit__category__legacy_exa_tags_mapped() -> None:
    assert CATEGORY_BY_TAG["recently_funded"] == "emerging"
    assert CATEGORY_BY_TAG["established_exa_discovery"] == "established"


def test_unit__category__own_and_similar_talent_brands_are_established() -> None:
    """S1 + S2: brands already partnered with the talent or their peers."""
    assert CATEGORY_BY_TAG["previous_brand_reengage"] == "established"
    assert CATEGORY_BY_TAG["similar_talent_worked_with"] == "established"


def test_unit__category__competitor_searches_are_established() -> None:
    """S3 + S4: competing with past brands implies commercial scale."""
    assert CATEGORY_BY_TAG["competitor_of_previous"] == "established"
    assert CATEGORY_BY_TAG["competitor_of_similar_talent"] == "established"


def test_unit__category__signal_overlay_tags_are_emerging() -> None:
    """Phase 4: trending/funded signals = emerging by definition."""
    assert CATEGORY_BY_TAG["global_trending_funded"] == "emerging"
    assert CATEGORY_BY_TAG["last30days_trending"] == "emerging"


# ── resolver behaviour ────────────────────────────────────────────


def test_unit__infer__first_mapped_tag_wins() -> None:
    """When sources stack (multiple tags), first match in iteration order wins."""
    out = infer_brand_category(
        ["values_aligned_exa", "exa_growth", "exa_established"],
        brand_entry=None,
    )
    assert out == "growth"  # exa_growth is the first mapped tag


def test_unit__infer__falls_back_to_brand_entry_category_when_no_tag_matches() -> None:
    """Tags like ``values_aligned_exa`` don't imply a category; entry wins."""
    out = infer_brand_category(["values_aligned_exa"], brand_entry={"brand_category": "growth"})
    assert out == "growth"


def test_unit__infer__brand_entry_only_used_when_no_tag_match() -> None:
    """A mapped tag beats the seed-entry fallback even if entry has a value."""
    out = infer_brand_category(["exa_emerging"], brand_entry={"brand_category": "established"})
    assert out == "emerging"


def test_unit__infer__invalid_entry_category_ignored() -> None:
    out = infer_brand_category(["values_aligned_exa"], brand_entry={"brand_category": "rocketship"})
    assert out is None


def test_unit__infer__no_tag_no_entry_returns_none() -> None:
    out = infer_brand_category(["values_aligned_exa"], brand_entry=None)
    assert out is None


def test_unit__infer__empty_tags_falls_back_to_entry() -> None:
    out = infer_brand_category([], brand_entry={"brand_category": "established"})
    assert out == "established"


def test_unit__infer__handles_non_string_tags_safely() -> None:
    out = infer_brand_category(
        [None, 42, "exa_established"],
        brand_entry=None,  # type: ignore[list-item]
    )
    assert out == "established"


def test_unit__infer__seed_map_walk_inherits_from_entry() -> None:
    """The seed-map walk's own tag is intentionally unmapped — relies on
    the seed-map entry's stored category to flow through."""
    assert "seed_map_walk" not in CATEGORY_BY_TAG
    out = infer_brand_category(["seed_map_walk"], brand_entry={"brand_category": "established"})
    assert out == "established"
