"""M7.3 — Search 15 query expansion (2 -> 7 variations + country embed)."""

from __future__ import annotations

from app.services.discovery import search_15_exa_newly_funded


def test_unit__s15_queries__seven_variations_per_industry() -> None:
    """The query builder returns 7 distinct variations."""
    queries = search_15_exa_newly_funded._build_queries_for_industry("activewear")  # pyright: ignore[reportPrivateUsage]
    assert len(queries) == 7
    assert len(set(queries)) == 7  # all unique


def test_unit__s15_queries__country_embedded_when_provided() -> None:
    """Talent country embeds into every variation."""
    queries = search_15_exa_newly_funded._build_queries_for_industry(  # pyright: ignore[reportPrivateUsage]
        "activewear", talent_country="US"
    )
    # All 7 queries reference US somewhere.
    for q in queries:
        assert "US" in q


def test_unit__s15_queries__country_omitted_when_missing() -> None:
    """No country -> queries fall back to global form (no double spaces)."""
    queries = search_15_exa_newly_funded._build_queries_for_industry(  # pyright: ignore[reportPrivateUsage]
        "activewear", talent_country=None
    )
    for q in queries:
        # Defensive: no leading whitespace, no double spaces from the geo slot.
        assert q == q.strip()
        assert "  " not in q


def test_unit__s15_queries__industry_id_pretty_printed() -> None:
    """Hyphens in the industry_id become spaces in the query (search-friendly)."""
    queries = search_15_exa_newly_funded._build_queries_for_industry(  # pyright: ignore[reportPrivateUsage]
        "home-improvement"
    )
    for q in queries:
        assert "home improvement" in q
        assert "home-improvement" not in q


def test_unit__s15_queries__cover_funded_emerging_indie_dtc_dimensions() -> None:
    """The 7 variations cover the major emerging-brand angles."""
    queries = search_15_exa_newly_funded._build_queries_for_industry("toys")  # pyright: ignore[reportPrivateUsage]
    joined = " ".join(queries).lower()
    # Each angle should be hit at least once across the variations.
    for keyword in ["newly funded", "series a", "emerging", "d2c", "indie", "to watch", "startup"]:
        assert keyword in joined
