"""Search 13 (LLM values-aligned classifier)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.discovery import search_13_values_aligned
from app.services.discovery._models import CandidateSource


def _brand_map(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"brands": list(entries)}


def _source(brand_name: str, industry_id: str, weight: float = 0.10) -> CandidateSource:
    return CandidateSource(
        brand_id=brand_name.lower().replace(" ", "-"),
        brand_name=brand_name,
        industry_id=industry_id,
        search_tag="other_search",
        weight=weight,
        note="seed",
    )


def _llm_response(text: str) -> MagicMock:
    """Build a mock anthropic response with a single text block."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


@pytest.mark.asyncio
async def test_unit__search_13__empty_preferences_returns_empty() -> None:
    sources = await search_13_values_aligned.run(
        brand_preferences={},
        surfaced_sources=[_source("Gymshark", "activewear")],
        brand_industry_map=_brand_map({"name": "Gymshark", "industry_id": "activewear"}),
    )
    assert sources == []


@pytest.mark.asyncio
async def test_unit__search_13__no_surfaced_sources_returns_empty() -> None:
    sources = await search_13_values_aligned.run(
        brand_preferences={"values_aligned_themes": ["sustainability"]},
        surfaced_sources=[],
        brand_industry_map=_brand_map({"name": "Patagonia", "industry_id": "outdoor"}),
    )
    assert sources == []


@pytest.mark.asyncio
async def test_unit__search_13__llm_aligned_brand_emits_source() -> None:
    bim = _brand_map(
        {"name": "Patagonia", "industry_id": "outdoor"},
        {"name": "Gymshark", "industry_id": "activewear"},
    )
    response = _llm_response(
        '{"aligned": [{"brand_name": "Patagonia", '
        '"rationale": "Mission-led sustainability brand."}]}'
    )
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)

    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        sources = await search_13_values_aligned.run(
            brand_preferences={"values_aligned_themes": ["sustainability"]},
            surfaced_sources=[
                _source("Patagonia", "outdoor"),
                _source("Gymshark", "activewear"),
            ],
            brand_industry_map=bim,
        )
    assert len(sources) == 1
    assert sources[0].brand_id == "patagonia"
    assert sources[0].search_tag == "values_aligned"
    assert sources[0].weight == 0.05
    assert sources[0].note == "Mission-led sustainability brand."


@pytest.mark.asyncio
async def test_unit__search_13__llm_response_wrapped_in_code_fences_still_parses() -> None:
    bim = _brand_map({"name": "Patagonia", "industry_id": "outdoor"})
    response = _llm_response(
        '```json\n{"aligned": [{"brand_name": "Patagonia", "rationale": "good"}]}\n```'
    )
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)

    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        sources = await search_13_values_aligned.run(
            brand_preferences={"values_aligned_themes": ["sustainability"]},
            surfaced_sources=[_source("Patagonia", "outdoor")],
            brand_industry_map=bim,
        )
    assert len(sources) == 1


@pytest.mark.asyncio
async def test_unit__search_13__llm_returns_invalid_json_returns_empty() -> None:
    bim = _brand_map({"name": "Patagonia", "industry_id": "outdoor"})
    response = _llm_response("not json at all just prose")
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)

    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        sources = await search_13_values_aligned.run(
            brand_preferences={"values_aligned_themes": ["x"]},
            surfaced_sources=[_source("Patagonia", "outdoor")],
            brand_industry_map=bim,
        )
    assert sources == []


@pytest.mark.asyncio
async def test_unit__search_13__llm_exception_returns_empty() -> None:
    bim = _brand_map({"name": "Patagonia", "industry_id": "outdoor"})
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=RuntimeError("API down"))

    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        sources = await search_13_values_aligned.run(
            brand_preferences={"values_aligned_themes": ["x"]},
            surfaced_sources=[_source("Patagonia", "outdoor")],
            brand_industry_map=bim,
        )
    assert sources == []


@pytest.mark.asyncio
async def test_unit__search_13__brand_not_in_seed_map_skipped() -> None:
    """LLM hallucinates a brand not in the seed map → no source emitted."""
    bim = _brand_map({"name": "Patagonia", "industry_id": "outdoor"})
    response = _llm_response('{"aligned": [{"brand_name": "MadeUpBrand", "rationale": "x"}]}')
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)

    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        sources = await search_13_values_aligned.run(
            brand_preferences={"values_aligned_themes": ["x"]},
            surfaced_sources=[_source("Patagonia", "outdoor")],
            brand_industry_map=bim,
        )
    assert sources == []


@pytest.mark.asyncio
async def test_unit__search_13__candidate_pool_capped() -> None:
    """When 100 sources surface, only the top max_candidates are sent to the LLM."""
    bim = _brand_map(*[{"name": f"Brand{i}", "industry_id": "x"} for i in range(100)])
    captured_prompt: dict[str, str] = {}

    async def _capture(**kwargs: Any) -> Any:
        captured_prompt["prompt"] = kwargs["messages"][0]["content"]
        return _llm_response('{"aligned": []}')

    client = MagicMock()
    client.messages.create = _capture
    surfaced = [_source(f"Brand{i}", "x", weight=float(i) / 100.0) for i in range(100)]

    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        await search_13_values_aligned.run(
            brand_preferences={"values_aligned_themes": ["x"]},
            surfaced_sources=surfaced,
            brand_industry_map=bim,
            max_candidates=5,
        )
    # The prompt should mention exactly 5 distinct brand names. Each
    # candidate appears as "  - Brand{i} (industry: x)" so use the
    # ' (industry:' suffix to count distinct mentions cleanly.
    prompt = captured_prompt["prompt"]
    assert prompt.count(" (industry: x)") == 5
    # And the top 5 by weight (Brand95..Brand99) should be the ones present.
    for i in range(95, 100):
        assert f"- Brand{i} (industry: x)" in prompt
