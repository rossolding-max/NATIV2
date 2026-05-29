"""Taxonomies.get_sub_industries (M7.3) — parent -> children lookup."""

from __future__ import annotations

import pytest

from app.utils.taxonomies import Taxonomies


@pytest.fixture(scope="module")
def tax() -> Taxonomies:
    """Load the real taxonomy files once for the module."""
    from pathlib import Path

    data_dir = Path(__file__).resolve().parents[3] / "data"
    return Taxonomies.from_directory(data_dir)


def test_unit__taxonomies__parent_industry_returns_children(tax: Taxonomies) -> None:
    """A top-level sector returns its sub-industries."""
    children = tax.get_sub_industries("sports-outdoor")
    assert len(children) > 0, "sports-outdoor sector must have child industries"
    # Sportswear should be there (Nike's industry).
    assert "sportswear" in children


def test_unit__taxonomies__leaf_industry_returns_empty(tax: Taxonomies) -> None:
    """A sub-industry that has no children returns []."""
    # Sportswear itself is a leaf (no grandchildren in the v0.1 taxonomy).
    leaf = tax.get_sub_industries("sportswear")
    assert leaf == []


def test_unit__taxonomies__unknown_industry_returns_empty(tax: Taxonomies) -> None:
    assert tax.get_sub_industries("definitely-not-a-real-industry") == []


def test_unit__taxonomies__children_are_deterministic(tax: Taxonomies) -> None:
    """Repeated calls return the same children in the same order (sorted)."""
    a = tax.get_sub_industries("food-beverage")
    b = tax.get_sub_industries("food-beverage")
    assert a == b
    assert a == sorted(a)


def test_unit__taxonomies__multiple_sectors_have_children(tax: Taxonomies) -> None:
    """At least 10 top-level sectors should have child industries
    (the test will catch a regression if the parent index ever breaks)."""
    sectors_with_children = sum(
        1 for industry_id in tax.industries if tax.get_sub_industries(industry_id)
    )
    assert sectors_with_children >= 10
