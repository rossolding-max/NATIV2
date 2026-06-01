"""Discovery search catalog (single source of truth)."""

from __future__ import annotations

from app.services.discovery.catalog import (
    KNOWN_SEARCH_NAMES,
    SEARCH_CATALOG,
    default_enabled_searches,
    validate_search_names,
)


def test_unit__catalog__has_all_18_searches() -> None:
    assert len(SEARCH_CATALOG) == 18
    # The catalog name should match the canonical "search_<N>_..." pattern.
    for info in SEARCH_CATALOG:
        assert info.name.startswith("search_")
        assert info.label
        assert info.description
        assert info.weight


def test_unit__catalog__known_names_matches_catalog() -> None:
    assert frozenset(s.name for s in SEARCH_CATALOG) == KNOWN_SEARCH_NAMES


def test_unit__catalog__default_enabled_returns_all_in_order() -> None:
    names = default_enabled_searches()
    assert len(names) == 18
    assert names == tuple(s.name for s in SEARCH_CATALOG)


def test_unit__catalog__search_17_listed_with_weight_range() -> None:
    by_name = {s.name: s for s in SEARCH_CATALOG}
    assert "search_17_paid_social_signal" in by_name
    info = by_name["search_17_paid_social_signal"]
    assert info.label == "Brands spending heavily on paid social"
    # Weight is a string range — single-platform 0.20 to multi-platform 0.30.
    assert "0.20" in info.weight
    assert "0.30" in info.weight


def test_unit__catalog__search_18_listed_with_weight_range() -> None:
    by_name = {s.name: s for s in SEARCH_CATALOG}
    assert "search_18_established_brands" in by_name
    info = by_name["search_18_established_brands"]
    assert info.label == "Established brands via Exa"
    assert "0.20" in info.weight
    assert "0.30" in info.weight
    assert info.requires_llm is True


def test_unit__catalog__validate_known_names_returns_empty() -> None:
    assert validate_search_names(["search_1_reengagement", "search_15_exa_newly_funded"]) == []


def test_unit__catalog__validate_returns_unknown_subset() -> None:
    unknown = validate_search_names(
        ["search_1_reengagement", "search_99_does_not_exist", "typo_search"]
    )
    assert unknown == ["search_99_does_not_exist", "typo_search"]


def test_unit__catalog__exposes_llm_and_skill_flags() -> None:
    """Frontend will render extra-cost / external-dependency badges from these."""
    by_name = {s.name: s for s in SEARCH_CATALOG}
    assert by_name["search_13_values_aligned"].requires_llm is True
    assert by_name["search_15_exa_newly_funded"].requires_llm is True
    assert by_name["search_16_last30days_trending"].requires_external_skill is True
    # Deterministic ones must not advertise external deps.
    assert by_name["search_1_reengagement"].requires_llm is False
    assert by_name["search_1_reengagement"].requires_external_skill is False
