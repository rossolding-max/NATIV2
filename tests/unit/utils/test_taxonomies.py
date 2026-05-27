"""Hardening tests for ``app.utils.taxonomies``.

Verifies file loading, lookup helpers, singleton lifecycle, and the
parent-fallback semantics documented in ``docs/architecture.md`` § 7.

Loads against the actual ``data/`` directory (not a fixture).
"""

from __future__ import annotations

import importlib

import pytest

from app.utils import taxonomies as taxonomies_module
from app.utils.taxonomies import get_taxonomies, init_taxonomies, is_loaded


@pytest.fixture(autouse=True)
def _reset_singleton() -> object:  # pyright: ignore[reportUnusedFunction]
    """Each test gets a fresh singleton (init_taxonomies binds the module-level
    `_singleton`; reset between tests to avoid leakage)."""
    importlib.reload(taxonomies_module)
    yield
    importlib.reload(taxonomies_module)


def test_unit__init_loads_full_corpus() -> None:
    """All 7 reference files load. Spot-check counts match observed totals."""
    tax = init_taxonomies()
    assert is_loaded()
    assert len(tax.niches) >= 100, f"niches loaded: {len(tax.niches)}"
    assert len(tax.industries) >= 150, f"industries loaded: {len(tax.industries)}"
    assert len(tax.iab_segments) >= 1000, f"iab loaded: {len(tax.iab_segments)}"
    assert len(tax.brand_competitors) >= 50, (
        f"brand competitors loaded: {len(tax.brand_competitors)}"
    )


def test_unit__get_taxonomies_raises_before_init() -> None:
    """Calling `get_taxonomies()` before `init_taxonomies()` is an error."""
    with pytest.raises(RuntimeError, match="not initialised"):
        get_taxonomies()


def test_unit__is_loaded_reflects_state() -> None:
    """`is_loaded` is False before init, True after."""
    assert not is_loaded()
    init_taxonomies()
    assert is_loaded()


def test_unit__niche_lookup_returns_node() -> None:
    tax = init_taxonomies()
    beauty = tax.get_niche("beauty")
    assert beauty is not None
    assert beauty["name"] == "Beauty"
    assert beauty["parent"] is None


def test_unit__niche_lookup_returns_none_for_unknown() -> None:
    tax = init_taxonomies()
    assert tax.get_niche("not-a-real-niche") is None


def test_unit__niche_parent_fallback() -> None:
    """Sub-niche `makeup` has parent `beauty`."""
    tax = init_taxonomies()
    parent = tax.get_niche_parent("makeup")
    assert parent == "beauty"
    assert tax.get_niche_parent("beauty") is None
    assert tax.get_niche_parent("does-not-exist") is None


def test_unit__niche_validation() -> None:
    tax = init_taxonomies()
    assert tax.is_valid_niche_id("beauty")
    assert not tax.is_valid_niche_id("not-a-niche")


def test_unit__industry_lookup_returns_node() -> None:
    tax = init_taxonomies()
    bpc = tax.get_industry("beauty-personal-care")
    assert bpc is not None
    assert bpc["parent"] is None


def test_unit__industry_parent_fallback() -> None:
    tax = init_taxonomies()
    assert tax.get_industry_parent("cosmetics") == "beauty-personal-care"


def test_unit__industry_sensitivity_flag() -> None:
    """Find one sensitive industry in the corpus (exists per the spec)."""
    tax = init_taxonomies()
    sensitive = [iid for iid, node in tax.industries.items() if node.get("sensitive")]
    assert len(sensitive) >= 1, "expected at least one sensitive industry in seed data"
    # Validate the helper agrees with the raw flag.
    for iid in sensitive:
        assert tax.is_sensitive_industry(iid)
    # And the negative case.
    assert not tax.is_sensitive_industry("beauty-personal-care")


def test_unit__competitor_lookup() -> None:
    tax = init_taxonomies()
    # Spot-check a known brand from the seed data.
    nike_competitors = tax.get_competitors("Nike")
    assert isinstance(nike_competitors, list)
    assert len(nike_competitors) > 0


def test_unit__competitor_empty_for_unknown_brand() -> None:
    tax = init_taxonomies()
    assert tax.get_competitors("Not A Real Brand") == []


def test_unit__iab_segment_lookup() -> None:
    """Root segment id=1 ('Demographic') is present per the IAB v1.1 taxonomy."""
    tax = init_taxonomies()
    root = tax.get_iab_segment(1)
    assert root is not None
    assert root["name"] == "Demographic"
    assert root["tier"] == 1
