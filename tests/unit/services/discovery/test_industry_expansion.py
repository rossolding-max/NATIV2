"""M7.4 — Bidirectional sub-industry walk + deal-industry extraction."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services.discovery._industry_expansion import (
    expand_past_deal_industries_bidirectionally,
    extract_industries_from_deals,
)


def _tax_with_hierarchy(
    parents: dict[str, str | None], children: dict[str, list[str]]
) -> MagicMock:
    """parents: child_industry_id -> parent_industry_id (None for top-level).
    children: parent_industry_id -> sorted list of child ids."""
    tax = MagicMock()
    tax.get_industry_parent.side_effect = lambda industry_id: parents.get(industry_id)  # pyright: ignore[reportUnknownLambdaType,reportUnknownArgumentType]
    tax.get_sub_industries.side_effect = lambda industry_id: children.get(industry_id, [])  # pyright: ignore[reportUnknownLambdaType,reportUnknownArgumentType]
    return tax


# ── expand_past_deal_industries_bidirectionally ────────────────────


def test_unit__bidirectional__sub_industry_expands_to_parent_and_siblings() -> None:
    """Sub-industry sportswear → sports-outdoor parent + all siblings."""
    tax = _tax_with_hierarchy(
        parents={
            "sportswear": "sports-outdoor",
            "outdoor-gear": "sports-outdoor",
            "gym-equipment": "sports-outdoor",
            "sports-outdoor": None,  # top-level sector
        },
        children={"sports-outdoor": ["gym-equipment", "outdoor-gear", "sportswear"]},
    )
    expanded = expand_past_deal_industries_bidirectionally(["sportswear"], tax)
    assert expanded == {"sportswear", "sports-outdoor", "outdoor-gear", "gym-equipment"}


def test_unit__bidirectional__top_level_sector_no_expansion() -> None:
    """Top-level sector (no parent) returns itself only."""
    tax = _tax_with_hierarchy(parents={"toys": None}, children={"toys": []})
    expanded = expand_past_deal_industries_bidirectionally(["toys"], tax)
    assert expanded == {"toys"}


def test_unit__bidirectional__multi_deal_unions_expansions() -> None:
    """Two deals with sub-industries in different parents union their expansions."""
    tax = _tax_with_hierarchy(
        parents={
            "sportswear": "sports-outdoor",
            "outdoor-gear": "sports-outdoor",
            "diapers-nappies": "baby-care",
            "baby-care": None,
            "sports-outdoor": None,
        },
        children={
            "sports-outdoor": ["outdoor-gear", "sportswear"],
            "baby-care": ["diapers-nappies"],
        },
    )
    expanded = expand_past_deal_industries_bidirectionally(["sportswear", "diapers-nappies"], tax)
    assert expanded == {
        "sportswear",
        "sports-outdoor",
        "outdoor-gear",
        "diapers-nappies",
        "baby-care",
    }


def test_unit__bidirectional__empty_input_returns_empty() -> None:
    tax = _tax_with_hierarchy(parents={}, children={})
    expanded = expand_past_deal_industries_bidirectionally([], tax)
    assert expanded == set()


def test_unit__bidirectional__skips_falsy_industry_ids() -> None:
    tax = _tax_with_hierarchy(parents={}, children={})
    expanded = expand_past_deal_industries_bidirectionally(["", None], tax)  # type: ignore[list-item]
    assert expanded == set()


# ── extract_industries_from_deals ─────────────────────────────────


def test_unit__deal_extract__pulls_industry_ids() -> None:
    deals = [
        {"brand_id": "nike", "industry_id": "sportswear"},
        {"brand_id": "huggies", "industry_id": "diapers-nappies"},
    ]
    assert extract_industries_from_deals(deals) == ["sportswear", "diapers-nappies"]


def test_unit__deal_extract__dedupes() -> None:
    deals = [
        {"brand_id": "nike", "industry_id": "sportswear"},
        {"brand_id": "adidas", "industry_id": "sportswear"},
    ]
    assert extract_industries_from_deals(deals) == ["sportswear"]


def test_unit__deal_extract__skips_non_dict_or_missing_industry() -> None:
    deals = [
        {"brand_id": "nike"},  # no industry_id
        "not a dict",  # not a dict
        {"industry_id": "fintech"},  # only industry_id
    ]
    assert extract_industries_from_deals(deals) == ["fintech"]
