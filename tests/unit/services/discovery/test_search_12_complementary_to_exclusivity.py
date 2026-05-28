"""Search 12 (industries complementary to active exclusivities)."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

from app.services.discovery import search_12_complementary_to_exclusivity


def _make_taxonomies(industries: dict[str, dict[str, Any]]) -> MagicMock:
    tax = MagicMock()
    tax.industries = industries

    def _get_industry(industry_id: str) -> dict[str, Any] | None:
        return industries.get(industry_id)

    tax.get_industry.side_effect = _get_industry
    return tax


def _brand_map(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"brands": list(entries)}


def test_unit__search_12__sibling_industries_emit_sources() -> None:
    """Exclusivity in 'activewear' (parent='fitness'); sibling 'sports-nutrition' surfaces."""
    industries = {
        "activewear": {"id": "activewear", "parent": "fitness"},
        "sports-nutrition": {"id": "sports-nutrition", "parent": "fitness"},
        "fitness": {"id": "fitness", "parent": None},
    }
    tax = _make_taxonomies(industries)
    bim = _brand_map(
        {"name": "MyProtein", "industry_id": "sports-nutrition"},
        {"name": "Gymshark", "industry_id": "activewear"},  # excluded (own industry)
    )
    sources = search_12_complementary_to_exclusivity.run(
        brand_preferences={
            "active_exclusivities": [{"industry_id": "activewear", "ends_on": "2030-01-01"}]
        },
        taxonomies=tax,
        brand_industry_map=bim,
        today=date(2026, 5, 1),
    )
    brand_ids = {s.brand_id for s in sources}
    assert "myprotein" in brand_ids
    assert "gymshark" not in brand_ids
    for s in sources:
        assert s.search_tag == "complementary_to_exclusivity"
        assert s.weight == 0.05


def test_unit__search_12__expired_exclusivity_ignored() -> None:
    industries = {
        "activewear": {"id": "activewear", "parent": "fitness"},
        "sports-nutrition": {"id": "sports-nutrition", "parent": "fitness"},
        "fitness": {"id": "fitness", "parent": None},
    }
    tax = _make_taxonomies(industries)
    bim = _brand_map({"name": "MyProtein", "industry_id": "sports-nutrition"})
    sources = search_12_complementary_to_exclusivity.run(
        brand_preferences={
            "active_exclusivities": [{"industry_id": "activewear", "ends_on": "2025-01-01"}]
        },
        taxonomies=tax,
        brand_industry_map=bim,
        today=date(2026, 5, 1),
    )
    assert sources == []


def test_unit__search_12__no_active_exclusivities_returns_empty() -> None:
    tax = _make_taxonomies({})
    sources = search_12_complementary_to_exclusivity.run(
        brand_preferences={"active_exclusivities": []},
        taxonomies=tax,
        brand_industry_map=_brand_map({"name": "X", "industry_id": "anything"}),
    )
    assert sources == []


def test_unit__search_12__missing_ends_on_treated_as_active() -> None:
    industries = {
        "activewear": {"id": "activewear", "parent": "fitness"},
        "sports-nutrition": {"id": "sports-nutrition", "parent": "fitness"},
        "fitness": {"id": "fitness", "parent": None},
    }
    tax = _make_taxonomies(industries)
    bim = _brand_map({"name": "MyProtein", "industry_id": "sports-nutrition"})
    sources = search_12_complementary_to_exclusivity.run(
        brand_preferences={"active_exclusivities": [{"industry_id": "activewear"}]},
        taxonomies=tax,
        brand_industry_map=bim,
        today=date(2026, 5, 1),
    )
    assert len(sources) == 1


def test_unit__search_12__exclusivity_with_no_parent_industry_returns_empty() -> None:
    industries = {"saas": {"id": "saas", "parent": None}}
    tax = _make_taxonomies(industries)
    bim = _brand_map({"name": "X", "industry_id": "anything"})
    sources = search_12_complementary_to_exclusivity.run(
        brand_preferences={
            "active_exclusivities": [{"industry_id": "saas", "ends_on": "2030-01-01"}]
        },
        taxonomies=tax,
        brand_industry_map=bim,
        today=date(2026, 5, 1),
    )
    assert sources == []
