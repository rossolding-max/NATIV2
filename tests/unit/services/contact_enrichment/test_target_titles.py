"""M8.1 — broad-keyword target-title resolution."""

from __future__ import annotations

from app.services.contact_enrichment.target_titles import (
    BROAD_TITLE_KEYWORDS,
    known_categories,
    resolve_target_titles,
)


def test_unit__target_titles__caller_supplied_wins() -> None:
    """Caller override beats the broad-keyword default."""
    out = resolve_target_titles(caller_supplied=["VP Marketing", "Brand Manager"])
    assert out == ["VP Marketing", "Brand Manager"]


def test_unit__target_titles__dedupes_caller_input() -> None:
    out = resolve_target_titles(caller_supplied=["VP Marketing", "VP Marketing", "  Brand Manager"])
    assert out == ["VP Marketing", "Brand Manager"]


def test_unit__target_titles__no_override_returns_broad_keywords() -> None:
    """Default path returns the M8.1 broad-keyword list verbatim."""
    out = resolve_target_titles(caller_supplied=None)
    assert out == BROAD_TITLE_KEYWORDS


def test_unit__target_titles__brand_category_is_ignored_in_m81() -> None:
    """The brand_category arg is retained for back-compat but no longer routes."""
    # Both calls must return the same broad list regardless of category.
    out_with_cat = resolve_target_titles(caller_supplied=None, brand_category="b2b-saas")
    out_without_cat = resolve_target_titles(caller_supplied=None, brand_category=None)
    assert out_with_cat == out_without_cat == BROAD_TITLE_KEYWORDS


def test_unit__target_titles__broad_list_covers_key_marketing_keywords() -> None:
    """The keyword list must cover the marketing-adjacent ecosystem we agreed."""
    required = {
        "marketing",
        "brand",
        "creator",
        "influencer",
        "partnerships",
        "social",
        "growth",
        "communications",
        "PR",
        "community",
        "affiliate",
        "founder",
    }
    assert required <= set(BROAD_TITLE_KEYWORDS)


def test_unit__target_titles__known_categories_empty_in_m81() -> None:
    """M8.1 removed category-specific routing; the catalog is empty."""
    assert known_categories() == []
