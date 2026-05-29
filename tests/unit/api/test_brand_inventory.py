"""M7.7+ — Brand inventory summary endpoint tests.

Tests the pure summariser. The route itself is covered by reading the
real merged seed map on disk; the unit tests below isolate the counter
logic so changes to the live data don't break the suite.
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.brand_inventory import _summarise  # pyright: ignore[reportPrivateUsage]


def test_unit__summarise__counts_by_industry_sorted_desc() -> None:
    brands = [
        {"name": "A", "industry_id": "toys"},
        {"name": "B", "industry_id": "toys"},
        {"name": "C", "industry_id": "grocery"},
    ]
    out = _summarise(brands)
    # toys has the higher count → appears first.
    assert next(iter(out["by_industry"].items())) == ("toys", 2)
    assert out["by_industry"]["grocery"] == 1


def test_unit__summarise__breaks_ties_by_id_asc() -> None:
    brands = [
        {"name": "A", "industry_id": "zzz"},
        {"name": "B", "industry_id": "aaa"},
    ]
    out = _summarise(brands)
    # Equal counts (1 each) → sorted by id ascending: aaa first.
    assert list(out["by_industry"].keys()) == ["aaa", "zzz"]


def test_unit__summarise__counts_sub_industries_separately() -> None:
    brands = [
        {"name": "A", "industry_id": "fashion", "sub_industry_id": "fashion-streetwear"},
        {"name": "B", "industry_id": "fashion", "sub_industry_id": "footwear"},
        {"name": "C", "industry_id": "fashion"},  # no sub → counted only top-level
    ]
    out = _summarise(brands)
    assert out["by_industry"]["fashion"] == 3
    assert out["by_sub_industry"] == {"fashion-streetwear": 1, "footwear": 1}


def test_unit__summarise__categorises_by_brand_category() -> None:
    brands = [
        {"name": "A", "industry_id": "toys", "brand_category": "emerging"},
        {"name": "B", "industry_id": "toys", "brand_category": "established"},
        {"name": "C", "industry_id": "toys"},  # no category → uncategorised
    ]
    out = _summarise(brands)
    assert out["by_brand_category"] == {
        "emerging": 1,
        "established": 1,
        "uncategorised": 1,
    }


def test_unit__summarise__counts_domain_and_social_handle_presence() -> None:
    brands = [
        {"name": "A", "industry_id": "toys", "domain": "a.com"},
        {"name": "B", "industry_id": "toys", "social_handles": {"instagram": "@b"}},
        {
            "name": "C",
            "industry_id": "toys",
            "domain": "c.com",
            "social_handles": {"tiktok": "@c"},
        },
        {"name": "D", "industry_id": "toys"},
    ]
    out = _summarise(brands)
    assert out["with_domain"] == 2
    assert out["with_social_handles"] == 2


def test_unit__summarise__skips_malformed_entries() -> None:
    brands = [
        "not a dict",  # type: ignore[list-item]
        {"name": "A", "industry_id": "toys"},
    ]
    out = _summarise(brands)
    assert out["by_industry"] == {"toys": 1}


def test_unit__summarise__defaults_source_to_curated_when_missing() -> None:
    brands = [
        {"name": "A", "industry_id": "toys"},  # no source → curated
        {"name": "B", "industry_id": "toys", "source": "exa_emerging"},
    ]
    out = _summarise(brands)
    assert out["by_source"] == {"curated": 1, "exa_emerging": 1}


# ── route smoke test ───────────────────────────────────────────────


def test_unit__route__summary_returns_envelope_shape() -> None:
    """End-to-end smoke against a stubbed seed map. Verifies the route
    wires through ``_summarise`` and emits the standard ``data/meta/errors``
    envelope expected of every NATIV2 endpoint."""
    from app.main import app

    stub_payload = {
        "version": 1,
        "updated_curated": "2026-01-01T00:00:00Z",
        "updated_discovered": "2026-05-01T00:00:00Z",
        "brands": [
            {"name": "Kudos", "industry_id": "diapers-nappies"},
            {"name": "Tesla", "industry_id": "auto-oems"},
        ],
    }
    with patch(
        "app.api.brand_inventory.load_merged_brand_industry_map",
        return_value=stub_payload,
    ):
        client = TestClient(app)
        resp = client.get("/api/v1/brand-inventory/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "meta" in body
    assert "errors" in body
    data = body["data"]
    assert data["total_brands"] == 2
    assert data["updated_curated"] == "2026-01-01T00:00:00Z"
    assert data["updated_discovered"] == "2026-05-01T00:00:00Z"
    assert data["by_industry"] == {"auto-oems": 1, "diapers-nappies": 1}
    assert body["errors"] == []
