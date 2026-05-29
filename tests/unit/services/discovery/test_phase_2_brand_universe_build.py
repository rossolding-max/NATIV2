"""M7.7 — Phase 2 brand universe build (3-category fan-out) tests."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.discovery import phase_2_brand_universe_build as p2


def _mock_tax(parents: dict[str, str | None]) -> MagicMock:
    tax = MagicMock()
    tax.get_industry_parent.side_effect = lambda iid: parents.get(iid)  # pyright: ignore[reportUnknownLambdaType,reportUnknownArgumentType]
    return tax


def _mock_exa(brand_names: list[str]) -> MagicMock:
    exa = MagicMock()
    exa.search = AsyncMock(
        return_value={
            "results": [
                {
                    "url": f"https://example.com/{n}",
                    "title": n,
                    "text": f"{n} is mentioned here.",
                }
                for n in brand_names
            ]
        }
    )
    return exa


def _mock_anthropic(brands: list[dict[str, Any]]) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps({"brands": brands})
    resp = MagicMock()
    resp.content = [block]
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=resp)
    return client


# ── Query builders ──────────────────────────────────────────────


def test_unit__p2_queries__emerging_has_seven_variants() -> None:
    qs = p2._build_queries(  # pyright: ignore[reportPrivateUsage]
        category="emerging", industry_id="diapers-nappies", talent_country="US"
    )
    assert len(qs) == 7
    assert all("US" in q for q in qs)
    assert all("diapers nappies" in q for q in qs)


def test_unit__p2_queries__growth_targets_mid_market_terms() -> None:
    qs = p2._build_queries(  # pyright: ignore[reportPrivateUsage]
        category="growth", industry_id="grocery", talent_country="US"
    )
    joined = " ".join(qs).lower()
    # Growth-band keywords cover the mid-market gap.
    for keyword in ["series c", "fast-growing", "regional", "mid-market"]:
        assert keyword in joined


def test_unit__p2_queries__established_six_variants() -> None:
    qs = p2._build_queries(  # pyright: ignore[reportPrivateUsage]
        category="established", industry_id="auto-oems", talent_country="US"
    )
    assert len(qs) == 6


# ── LLM extraction ──────────────────────────────────────────────


def test_unit__p2_parse__strips_below_confidence() -> None:
    raw = json.dumps(
        {
            "brands": [
                {"brand_name": "Yes", "confidence": 0.92, "evidence": "x"},
                {"brand_name": "No", "confidence": 0.5, "evidence": "y"},
            ]
        }
    )
    out = p2._parse_llm_response(raw, fallback_industry_id="toys")  # pyright: ignore[reportPrivateUsage]
    assert len(out) == 1
    assert out[0]["brand_name"] == "Yes"


# ── Full run() ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unit__p2_run__three_categories_each_emit_distinct_tag() -> None:
    """Each category fan-out emits the right search_tag on its sources."""
    tax = _mock_tax({"toys": None})
    exa = _mock_exa(["Mattel"])
    anth = _mock_anthropic(
        [
            {
                "brand_name": "Mattel",
                "suggested_industry_id": "toys",
                "confidence": 0.92,
                "evidence": "Listed",
                "source_url": "https://example.com/Mattel",
            }
        ]
    )

    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=anth),
        patch(
            "app.services.discovery.phase_2_brand_universe_build."
            "enrich_extracted_brands_inplace",
            new=AsyncMock(return_value=None),
        ),
    ):
        sources = await p2.run(
            approved_industries=["toys"],
            brand_industry_map={"brands": []},
            taxonomies=tax,
            talent_country="US",
            categories=["emerging", "growth", "established"],
            results_per_query=1,
        )

    tags = {s.search_tag for s in sources}
    assert tags == {"exa_emerging", "exa_growth", "exa_established"}
    # Note carries category metadata.
    sample = sources[0]
    assert "category=" in sample.note


@pytest.mark.asyncio
async def test_unit__p2_run__canonicalises_to_seed_brand() -> None:
    """When the extracted name matches a seed entry, emit on canonical brand_id."""
    tax = _mock_tax({"auto-oems": "auto", "auto": None})
    exa = _mock_exa(["Ford Motor Company"])
    anth = _mock_anthropic(
        [
            {
                "brand_name": "Ford Motor Company",
                "suggested_industry_id": "auto-oems",
                "confidence": 0.95,
                "evidence": "Top US auto.",
                "source_url": "https://example.com/Ford Motor Company",
            }
        ]
    )
    seed = {
        "brands": [
            {"brand_id": "ford", "name": "Ford", "industry_id": "auto-oems"},
        ]
    }

    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=anth),
        patch(
            "app.services.discovery.phase_2_brand_universe_build."
            "enrich_extracted_brands_inplace",
            new=AsyncMock(return_value=None),
        ),
    ):
        sources = await p2.run(
            approved_industries=["auto-oems"],
            brand_industry_map=seed,
            taxonomies=tax,
            categories=["emerging"],
            results_per_query=1,
        )

    assert all(s.brand_id == "ford" for s in sources)
    assert all(s.brand_name == "Ford" for s in sources)
    # Note records the canonicalisation.
    assert "canonicalised from" in sources[0].note


@pytest.mark.asyncio
async def test_unit__p2_run__empty_industries_returns_empty() -> None:
    tax = _mock_tax({})
    sources = await p2.run(
        approved_industries=[],
        brand_industry_map={"brands": []},
        taxonomies=tax,
    )
    assert sources == []


@pytest.mark.asyncio
async def test_unit__p2_run__provenance_fields_populated_per_source() -> None:
    """Every emitted source carries exa_query, exa_result_url, exa_result_title."""
    tax = _mock_tax({"grocery": None})
    exa = _mock_exa(["Kroger"])
    anth = _mock_anthropic(
        [
            {
                "brand_name": "Kroger",
                "suggested_industry_id": "grocery",
                "confidence": 0.88,
                "evidence": "Mentioned",
                "source_url": "https://example.com/Kroger",
                "domain": "kroger.com",
                "social_handles": {"linkedin": "linkedin.com/company/kroger"},
            }
        ]
    )

    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=anth),
        patch(
            "app.services.discovery.phase_2_brand_universe_build."
            "enrich_extracted_brands_inplace",
            new=AsyncMock(return_value=None),
        ),
    ):
        sources = await p2.run(
            approved_industries=["grocery"],
            brand_industry_map={"brands": []},
            taxonomies=tax,
            categories=["emerging"],
            results_per_query=1,
        )

    # Multiple query variants per category → multiple sources for the same brand.
    assert len(sources) >= 1
    for s in sources:
        assert s.exa_query is not None
        assert s.exa_result_url == "https://example.com/Kroger"
        assert s.exa_result_title == "Kroger"
        assert s.brand_domain == "kroger.com"
        assert (s.brand_social_handles or {}).get("linkedin")
