"""Search 8 (parent + sibling niche expansion)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from app.services.discovery import search_8_parent_sibling_niche


def _make_taxonomies(
    niches: dict[str, dict[str, Any]],
    niche_industry_affinity: dict[str, Any] | None = None,
) -> MagicMock:
    tax = MagicMock()
    tax.niches = niches
    tax.niche_industry_affinity = niche_industry_affinity or {"groups": []}

    def _get_niche(niche_id: str) -> dict[str, Any] | None:
        return niches.get(niche_id)

    tax.get_niche.side_effect = _get_niche
    return tax


def _brand_map(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"brands": list(entries)}


def test_unit__search_8__sibling_niche_primary_industry_emits_source() -> None:
    """Talent in 'fitness-training'; sibling 'home-gym' → primary industry 'activewear'."""
    niches = {
        "fitness-training": {"id": "fitness-training", "parent": "fitness"},
        "home-gym": {"id": "home-gym", "parent": "fitness"},
    }
    affinity = {"groups": [{"niche_id": "home-gym", "primary": ["activewear"]}]}
    tax = _make_taxonomies(niches, affinity)
    bim = _brand_map({"name": "Gymshark", "industry_id": "activewear"})
    sources = search_8_parent_sibling_niche.run(
        content_niches=["fitness-training"],
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    assert sources[0].brand_id == "gymshark"
    assert sources[0].search_tag == "parent_sibling_niche"
    assert sources[0].weight == 0.08


def test_unit__search_8__parent_niche_primary_industry_emits_source() -> None:
    """Talent in 'fitness-training'; parent niche 'fitness' itself has a primary industry."""
    niches = {
        "fitness-training": {"id": "fitness-training", "parent": "fitness"},
        "fitness": {"id": "fitness", "parent": None},
    }
    affinity = {"groups": [{"niche_id": "fitness", "primary": ["sportswear"]}]}
    tax = _make_taxonomies(niches, affinity)
    bim = _brand_map({"name": "Nike", "industry_id": "sportswear"})
    sources = search_8_parent_sibling_niche.run(
        content_niches=["fitness-training"],
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    assert sources[0].industry_id == "sportswear"


def test_unit__search_8__own_niches_excluded_from_expansion() -> None:
    """Talent in BOTH 'fitness-training' and 'home-gym' → no expansion since both
    are already in own_niches (Search 5/6/7 already surfaced their industries)."""
    niches = {
        "fitness-training": {"id": "fitness-training", "parent": "fitness"},
        "home-gym": {"id": "home-gym", "parent": "fitness"},
    }
    affinity = {"groups": [{"niche_id": "fitness", "primary": ["sportswear"]}]}
    tax = _make_taxonomies(niches, affinity)
    bim = _brand_map({"name": "Nike", "industry_id": "sportswear"})
    sources = search_8_parent_sibling_niche.run(
        content_niches=["fitness-training", "home-gym"],
        taxonomies=tax,
        brand_industry_map=bim,
    )
    # Parent ('fitness') is still surfaced as adjacent because it's not in own_niches.
    assert len(sources) == 1
    assert sources[0].industry_id == "sportswear"


def test_unit__search_8__niche_with_no_parent_skipped() -> None:
    niches = {"travel": {"id": "travel", "parent": None}}
    tax = _make_taxonomies(niches, {"groups": []})
    sources = search_8_parent_sibling_niche.run(
        content_niches=["travel"],
        taxonomies=tax,
        brand_industry_map=_brand_map(),
    )
    assert sources == []


def test_unit__search_8__dedupes_brands_across_sibling_industries() -> None:
    """If two adjacent niches map to the same industry, the brand surfaces once."""
    niches = {
        "fitness-training": {"id": "fitness-training", "parent": "fitness"},
        "home-gym": {"id": "home-gym", "parent": "fitness"},
        "outdoor-sports": {"id": "outdoor-sports", "parent": "fitness"},
    }
    affinity = {
        "groups": [
            {"niche_id": "home-gym", "primary": ["activewear"]},
            {"niche_id": "outdoor-sports", "primary": ["activewear"]},
        ]
    }
    tax = _make_taxonomies(niches, affinity)
    bim = _brand_map({"name": "Gymshark", "industry_id": "activewear"})
    sources = search_8_parent_sibling_niche.run(
        content_niches=["fitness-training"],
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert len(sources) == 1
