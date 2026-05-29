"""M7.7+ — Cross-sector industry adjacency tests."""

from __future__ import annotations

from app.services.discovery._industry_adjacency import (
    _build_index_from_pairs,  # pyright: ignore[reportPrivateUsage]
    adjacent_industries,
)


def test_unit__adjacency__lookup_is_bidirectional() -> None:
    pairs = [{"from": "hotels", "to": "luggage-travel-gear", "reason": "travelers buy luggage"}]
    out_hotels = adjacent_industries("hotels", pairs=pairs)
    out_luggage = adjacent_industries("luggage-travel-gear", pairs=pairs)
    assert ("luggage-travel-gear", "travelers buy luggage") in out_hotels
    assert ("hotels", "travelers buy luggage") in out_luggage


def test_unit__adjacency__multiple_adjacencies_per_industry() -> None:
    pairs = [
        {"from": "auto-oems", "to": "tyres", "reason": "aftermarket"},
        {"from": "auto-oems", "to": "auto-insurance", "reason": "car owner buys insurance"},
    ]
    out = adjacent_industries("auto-oems", pairs=pairs)
    ids = {adj for adj, _ in out}
    assert ids == {"tyres", "auto-insurance"}


def test_unit__adjacency__unknown_industry_returns_empty() -> None:
    pairs = [{"from": "hotels", "to": "luggage-travel-gear", "reason": "x"}]
    assert adjacent_industries("not-in-table", pairs=pairs) == []


def test_unit__adjacency__self_pair_skipped() -> None:
    pairs = [{"from": "hotels", "to": "hotels", "reason": "self"}]
    assert adjacent_industries("hotels", pairs=pairs) == []


def test_unit__adjacency__duplicate_pair_dedup() -> None:
    pairs = [
        {"from": "hotels", "to": "luggage", "reason": "x"},
        {"from": "hotels", "to": "luggage", "reason": "x"},
    ]
    out = adjacent_industries("hotels", pairs=pairs)
    assert len(out) == 1


def test_unit__adjacency__build_index_skips_missing_fields() -> None:
    pairs = [
        {"from": "", "to": "x", "reason": "empty from"},
        {"to": "y", "reason": "missing from"},
        {"from": "a", "to": "b", "reason": "valid"},
    ]
    idx = _build_index_from_pairs(pairs)  # pyright: ignore[reportArgumentType]
    assert set(idx.keys()) == {"a", "b"}


def test_unit__adjacency__file_loaded_for_real_kevin_seed() -> None:
    """Sanity check the shipped data/industry_adjacency.json has the
    Kevin-relevant pairs (hotels, eyewear, sports-nutrition)."""
    hotel_adj = {adj for adj, _ in adjacent_industries("hotels")}
    assert "luggage-travel-gear" in hotel_adj
    eyewear_adj = {adj for adj, _ in adjacent_industries("eyewear")}
    assert "luxury-goods" in eyewear_adj
    sports_nut_adj = {adj for adj, _ in adjacent_industries("sports-nutrition")}
    assert "supplements-brands" in sports_nut_adj
