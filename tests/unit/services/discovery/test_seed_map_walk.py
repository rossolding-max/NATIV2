"""M7.7+ — Seed-map walk tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from app.services.discovery._seed_map_walk import SEARCH_TAG, run


def _tax(*, sub_industries: dict[str, list[str]] | None = None) -> Any:
    """Mock Taxonomies; ``get_sub_industries`` returns children per industry."""
    children = sub_industries or {}
    tax = MagicMock()
    tax.get_sub_industries.side_effect = lambda iid: children.get(iid, [])  # pyright: ignore[reportUnknownLambdaType,reportUnknownArgumentType]
    return tax


def _bim(brands: list[dict[str, Any]]) -> dict[str, Any]:
    return {"version": 1, "brands": brands}


# ── basic emission ────────────────────────────────────────────────


def test_unit__walk__emits_brand_matching_approved_industry() -> None:
    bim = _bim(
        [
            {"brand_id": "kudos", "name": "Kudos", "industry_id": "diapers-nappies"},
            {"brand_id": "tesla", "name": "Tesla", "industry_id": "auto-oems"},
        ]
    )
    sources = run(
        approved_industries=["diapers-nappies"],
        brand_industry_map=bim,
        taxonomies=_tax(),
    )
    assert len(sources) == 1
    s = sources[0]
    assert s.brand_id == "kudos"
    assert s.brand_name == "Kudos"
    assert s.industry_id == "diapers-nappies"
    assert s.search_tag == SEARCH_TAG
    assert s.weight == 0.30
    assert "Seed-map walk" in s.note
    assert "diapers-nappies" in s.note


def test_unit__walk__no_approved_industries_returns_empty() -> None:
    bim = _bim([{"brand_id": "x", "name": "X", "industry_id": "toys"}])
    assert run(approved_industries=[], brand_industry_map=bim, taxonomies=_tax()) == []


def test_unit__walk__empty_seed_map_returns_empty() -> None:
    assert run(approved_industries=["toys"], brand_industry_map=_bim([]), taxonomies=_tax()) == []


def test_unit__walk__skips_brands_outside_approved_set() -> None:
    bim = _bim(
        [
            {"brand_id": "a", "name": "A", "industry_id": "toys"},
            {"brand_id": "b", "name": "B", "industry_id": "grocery"},
        ]
    )
    sources = run(approved_industries=["toys"], brand_industry_map=bim, taxonomies=_tax())
    assert {s.brand_id for s in sources} == {"a"}


# ── sub-industry expansion ────────────────────────────────────────


def test_unit__walk__expands_top_level_into_sub_industries() -> None:
    """Approving ``fashion`` should surface brands tagged with child industries."""
    bim = _bim(
        [
            {"brand_id": "supreme", "name": "Supreme", "industry_id": "fashion-streetwear"},
            {"brand_id": "nike", "name": "Nike", "industry_id": "footwear"},
            {"brand_id": "ford", "name": "Ford", "industry_id": "auto-oems"},
        ]
    )
    tax = _tax(sub_industries={"fashion": ["fashion-streetwear", "footwear"]})
    sources = run(approved_industries=["fashion"], brand_industry_map=bim, taxonomies=tax)
    ids = {s.brand_id for s in sources}
    assert ids == {"supreme", "nike"}
    # Auto OEMs not in fashion subtree → excluded.


def test_unit__walk__matches_via_sub_industry_id_field() -> None:
    """Brands tagged with industry_id=parent + sub_industry_id=leaf surface
    when EITHER field matches."""
    bim = _bim(
        [
            {
                "brand_id": "marriott",
                "name": "Marriott",
                "industry_id": "travel-hospitality",
                "sub_industry_id": "hotels",
            }
        ]
    )
    # Operator approved the leaf only.
    sources = run(approved_industries=["hotels"], brand_industry_map=bim, taxonomies=_tax())
    assert len(sources) == 1
    assert sources[0].brand_id == "marriott"


# ── dedupe + metadata propagation ─────────────────────────────────


def test_unit__walk__dedupes_brand_appearing_twice() -> None:
    bim = _bim(
        [
            {"brand_id": "kudos", "name": "Kudos", "industry_id": "diapers-nappies"},
            {"brand_id": "kudos", "name": "Kudos", "industry_id": "diapers-nappies"},
        ]
    )
    sources = run(
        approved_industries=["diapers-nappies"],
        brand_industry_map=bim,
        taxonomies=_tax(),
    )
    assert len(sources) == 1


def test_unit__walk__derives_brand_id_when_missing() -> None:
    bim = _bim([{"name": "Hatch Collection", "industry_id": "maternity-baby-care"}])
    sources = run(
        approved_industries=["maternity-baby-care"],
        brand_industry_map=bim,
        taxonomies=_tax(),
    )
    assert len(sources) == 1
    assert sources[0].brand_id == "hatch-collection"


def test_unit__walk__propagates_domain_and_social_handles() -> None:
    bim = _bim(
        [
            {
                "brand_id": "kudos",
                "name": "Kudos",
                "industry_id": "diapers-nappies",
                "domain": "mykudos.com",
                "social_handles": {"instagram": "@kudos", "tiktok": None},
            }
        ]
    )
    sources = run(
        approved_industries=["diapers-nappies"],
        brand_industry_map=bim,
        taxonomies=_tax(),
    )
    assert sources[0].brand_domain == "mykudos.com"
    assert sources[0].brand_social_handles == {"instagram": "@kudos", "tiktok": None}


def test_unit__walk__skips_malformed_seed_entries() -> None:
    """Entries with no name, or non-dict, are skipped without erroring."""
    bim = _bim(
        [
            "not a dict",  # type: ignore[list-item]
            {"brand_id": "no-name", "industry_id": "toys"},  # missing name
            {"name": "", "industry_id": "toys"},  # empty name
            {"brand_id": "valid", "name": "Valid", "industry_id": "toys"},
        ]
    )
    sources = run(approved_industries=["toys"], brand_industry_map=bim, taxonomies=_tax())
    assert {s.brand_id for s in sources} == {"valid"}
