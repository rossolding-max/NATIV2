"""Default target-title resolution per brand category."""

from __future__ import annotations

from app.services.contact_enrichment.target_titles import (
    known_categories,
    resolve_target_titles,
)


def test_unit__target_titles__caller_supplied_wins() -> None:
    out = resolve_target_titles(
        caller_supplied=["VP Marketing", "Brand Manager"],
        brand_category="consumer-goods",
    )
    assert out == ["VP Marketing", "Brand Manager"]


def test_unit__target_titles__dedupes_caller_input() -> None:
    out = resolve_target_titles(
        caller_supplied=["VP Marketing", "VP Marketing", "  Brand Manager"],
        brand_category=None,
    )
    assert out == ["VP Marketing", "Brand Manager"]


def test_unit__target_titles__category_default() -> None:
    out = resolve_target_titles(caller_supplied=None, brand_category="b2b-saas")
    assert "VP Marketing" in out
    assert all(isinstance(t, str) for t in out)


def test_unit__target_titles__unknown_category_falls_back_to_consumer_goods() -> None:
    out = resolve_target_titles(caller_supplied=None, brand_category="mystery-category")
    assert "Head of Influencer Marketing" in out  # consumer-goods default


def test_unit__target_titles__none_category_uses_consumer_goods() -> None:
    out = resolve_target_titles(caller_supplied=None, brand_category=None)
    assert "Head of Influencer Marketing" in out


def test_unit__target_titles__known_categories_listed() -> None:
    cats = known_categories()
    assert "consumer-goods" in cats
    assert "b2b-saas" in cats
    assert "agency" in cats
