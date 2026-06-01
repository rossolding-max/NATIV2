"""M7.7 — Exclusivity-adjacent → industry derivation tests."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

from app.services.discovery._industry_from_exclusivity import (
    derive_industries_from_exclusivities,
)


def _mock_tax(
    industries: dict[str, dict[str, Any]],
) -> MagicMock:
    tax = MagicMock()
    tax.industries = industries
    tax.get_industry.side_effect = lambda industry_id: industries.get(industry_id)  # pyright: ignore[reportUnknownLambdaType,reportUnknownArgumentType]
    return tax


def test_unit__exclusivity__surfaces_siblings_and_parent_drops_self() -> None:
    """Activewear (parent sports-outdoor) → siblings + parent, NOT activewear itself."""
    tax = _mock_tax(
        {
            "sports-outdoor": {"id": "sports-outdoor", "parent": None},
            "activewear": {"id": "activewear", "parent": "sports-outdoor"},
            "sportswear": {"id": "sportswear", "parent": "sports-outdoor"},
            "outdoor-gear": {"id": "outdoor-gear", "parent": "sports-outdoor"},
        }
    )
    brand_preferences = {
        "active_exclusivities": [{"brand": "Gymshark", "industry_id": "activewear"}]
    }
    out = derive_industries_from_exclusivities(
        brand_preferences=brand_preferences, taxonomies=tax, today=date(2026, 5, 29)
    )
    ids = {p.industry_id for p in out}
    # Parent + siblings; the exclusivity industry itself dropped.
    assert ids == {"sports-outdoor", "sportswear", "outdoor-gear"}
    # Rationale names the brand.
    for p in out:
        assert "Gymshark" in p.rationale
        assert p.source == "exclusivity_adjacent"


def test_unit__exclusivity__expired_excl_skipped() -> None:
    tax = _mock_tax(
        {
            "sports-outdoor": {"id": "sports-outdoor", "parent": None},
            "activewear": {"id": "activewear", "parent": "sports-outdoor"},
        }
    )
    brand_preferences = {
        "active_exclusivities": [
            {
                "brand": "Gymshark",
                "industry_id": "activewear",
                "ends_on": "2024-01-01",  # expired well before today
            }
        ]
    }
    out = derive_industries_from_exclusivities(
        brand_preferences=brand_preferences, taxonomies=tax, today=date(2026, 5, 29)
    )
    assert out == []


def test_unit__exclusivity__empty_when_no_exclusivities() -> None:
    tax = _mock_tax({})
    out = derive_industries_from_exclusivities(brand_preferences={}, taxonomies=tax)
    assert out == []


def test_unit__exclusivity__top_level_exclusive_yields_only_siblings() -> None:
    """If the exclusivity industry has no parent (e.g. 'grocery'), no siblings, no adjacent."""
    tax = _mock_tax({"grocery": {"id": "grocery", "parent": None}})
    brand_preferences = {
        "active_exclusivities": [{"brand": "Whole Foods", "industry_id": "grocery"}]
    }
    out = derive_industries_from_exclusivities(
        brand_preferences=brand_preferences, taxonomies=tax, today=date(2026, 5, 29)
    )
    assert out == []
