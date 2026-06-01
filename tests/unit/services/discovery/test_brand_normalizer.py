"""M7.4 — Brand-name canonicalization tests."""

from __future__ import annotations

from app.services.discovery._brand_normalizer import (
    find_canonical_seed_entry,
    normalize_brand_name,
)

# ── normalize_brand_name ──────────────────────────────────────────


def test_unit__normalizer__strips_motor_company_suffix() -> None:
    assert normalize_brand_name("Ford Motor Company") == "ford"


def test_unit__normalizer__strips_corp_suffix() -> None:
    assert normalize_brand_name("Apple Inc") == "apple"
    assert normalize_brand_name("Microsoft Corporation") == "microsoft"
    assert normalize_brand_name("Tesla, Inc.") == "tesla"


def test_unit__normalizer__strips_leading_the() -> None:
    assert normalize_brand_name("The Kroger Co") == "kroger"
    assert normalize_brand_name("The Home Depot") == "home depot"


def test_unit__normalizer__multi_suffix_iterates() -> None:
    """'The Walt Disney Company Holdings' iteratively strips Holdings then Company."""
    assert normalize_brand_name("The Walt Disney Company Holdings") == "walt disney"


def test_unit__normalizer__protects_against_eating_whole_name() -> None:
    """A single-word suffix-like name should NOT be stripped to empty."""
    assert normalize_brand_name("Group") == "group"
    assert normalize_brand_name("Inc") == "inc"
    assert normalize_brand_name("Co") == "co"


def test_unit__normalizer__keeps_brand_when_no_suffix() -> None:
    assert normalize_brand_name("Bumble Bizz") == "bumble bizz"
    assert normalize_brand_name("Coca-Cola") == "coca cola"


def test_unit__normalizer__empty_or_whitespace_returns_empty() -> None:
    assert normalize_brand_name("") == ""
    assert normalize_brand_name("   ") == ""
    assert normalize_brand_name("&&&") == ""


def test_unit__normalizer__idempotent() -> None:
    sample = "Ford Motor Company"
    once = normalize_brand_name(sample)
    twice = normalize_brand_name(once)
    assert once == twice


# ── find_canonical_seed_entry ─────────────────────────────────────


def _seed_brands() -> list[dict]:  # type: ignore[type-arg]
    return [
        {"brand_id": "ford", "name": "Ford", "industry_id": "auto-oems"},
        {"brand_id": "gm", "name": "GM", "industry_id": "auto-oems", "aliases": ["General Motors"]},
        {"brand_id": "kroger", "name": "Kroger", "industry_id": "grocery"},
        {"brand_id": "apple", "name": "Apple", "industry_id": "consumer-electronics"},
    ]


def test_unit__canonical_seed__motor_company_matches_ford() -> None:
    match = find_canonical_seed_entry("Ford Motor Company", _seed_brands())
    assert match is not None
    assert match["brand_id"] == "ford"


def test_unit__canonical_seed__alias_match() -> None:
    """'General Motors' should match the GM seed entry via its aliases list."""
    match = find_canonical_seed_entry("General Motors", _seed_brands())
    assert match is not None
    assert match["brand_id"] == "gm"


def test_unit__canonical_seed__the_prefix_match() -> None:
    """'The Kroger Co' normalises to 'kroger' and matches the Kroger seed entry."""
    match = find_canonical_seed_entry("The Kroger Co", _seed_brands())
    assert match is not None
    assert match["brand_id"] == "kroger"


def test_unit__canonical_seed__no_match_returns_none() -> None:
    match = find_canonical_seed_entry("Random Indie Brand", _seed_brands())
    assert match is None


def test_unit__canonical_seed__empty_input_returns_none() -> None:
    assert find_canonical_seed_entry("", _seed_brands()) is None
    assert find_canonical_seed_entry("   ", _seed_brands()) is None
