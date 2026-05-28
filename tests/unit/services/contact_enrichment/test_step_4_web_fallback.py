"""Step 4 — Exa web-search fallback + LLM extract."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.contact_enrichment import step_4_web_fallback
from app.services.contact_enrichment._models import EnrichedContact


def _llm_response(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


def _filled_contact(title: str) -> EnrichedContact:
    return EnrichedContact(
        contact_id=f"bc_filled_{title.lower().replace(' ', '_')}",
        brand_id="gymshark",
        name="Already Filled",
        title=title,
    )


@pytest.mark.asyncio
async def test_unit__step_4__all_titles_filled_returns_empty() -> None:
    contacts = await step_4_web_fallback.run(
        brand_id="gymshark",
        brand_name="Gymshark",
        target_titles=["VP Marketing"],
        already_filled=[_filled_contact("VP Marketing")],
    )
    assert contacts == []


@pytest.mark.asyncio
async def test_unit__step_4__unfilled_title_runs_exa_and_llm() -> None:
    exa = MagicMock()
    exa.search = AsyncMock(
        return_value={
            "results": [
                {"url": "https://example.com", "text": "Jane Doe is VP of Brand at Gymshark."}
            ]
        }
    )
    response = _llm_response(
        '{"matches": [{"name": "Jane Doe", "title": "VP Brand", '
        '"linkedin_url": "https://linkedin.com/in/jdoe", "confidence": 0.9}]}'
    )
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)

    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=client),
    ):
        contacts = await step_4_web_fallback.run(
            brand_id="gymshark",
            brand_name="Gymshark",
            target_titles=["VP Brand"],
            already_filled=[],
        )
    assert len(contacts) == 1
    assert contacts[0].name == "Jane Doe"
    assert contacts[0].title == "VP Brand"
    assert contacts[0].linkedin_url == "https://linkedin.com/in/jdoe"


@pytest.mark.asyncio
async def test_unit__step_4__cap_on_unfilled_titles() -> None:
    """max_unfilled=2 means only 2 Exa queries fire even with 5 unfilled titles."""
    exa = MagicMock()
    exa.search = AsyncMock(return_value={"results": []})  # no results, but Exa called

    client = MagicMock()
    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=client),
    ):
        await step_4_web_fallback.run(
            brand_id="gymshark",
            brand_name="Gymshark",
            target_titles=["a", "b", "c", "d", "e"],
            already_filled=[],
            max_unfilled=2,
        )
    assert exa.search.call_count == 2


@pytest.mark.asyncio
async def test_unit__step_4__exa_failure_failsoft() -> None:
    exa = MagicMock()
    exa.search = AsyncMock(side_effect=RuntimeError("Exa rate-limited"))
    client = MagicMock()
    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=client),
    ):
        contacts = await step_4_web_fallback.run(
            brand_id="gymshark",
            brand_name="Gymshark",
            target_titles=["VP Brand"],
            already_filled=[],
        )
    assert contacts == []


@pytest.mark.asyncio
async def test_unit__step_4__skips_already_seen_linkedin_urls() -> None:
    """LLM hallucinates a contact already in already_filled -> dropped."""
    exa = MagicMock()
    exa.search = AsyncMock(return_value={"results": [{"url": "x", "text": "..."}]})
    response = _llm_response(
        '{"matches": [{"name": "Already Filled", '
        '"linkedin_url": "https://linkedin.com/in/af", "confidence": 0.8}]}'
    )
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    already = EnrichedContact(
        contact_id="bc_af",
        brand_id="gymshark",
        name="Already Filled",
        linkedin_url="https://linkedin.com/in/af",
    )
    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=client),
    ):
        contacts = await step_4_web_fallback.run(
            brand_id="gymshark",
            brand_name="Gymshark",
            target_titles=["VP Brand"],
            already_filled=[already],
        )
    assert contacts == []


@pytest.mark.asyncio
async def test_unit__step_4__llm_invalid_json_returns_empty() -> None:
    exa = MagicMock()
    exa.search = AsyncMock(return_value={"results": [{"url": "x", "text": "..."}]})
    response = _llm_response("totally not json")
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=client),
    ):
        contacts = await step_4_web_fallback.run(
            brand_id="gymshark",
            brand_name="Gymshark",
            target_titles=["VP Brand"],
            already_filled=[],
        )
    assert contacts == []


@pytest.mark.asyncio
async def test_unit__step_4__no_target_titles_returns_empty() -> None:
    out = await step_4_web_fallback.run(
        brand_id="gymshark",
        brand_name="Gymshark",
        target_titles=[],
        already_filled=[],
    )
    assert out == []


def test_unit__step_4__parse_response_strips_code_fences() -> None:
    matches = step_4_web_fallback._parse_response(  # pyright: ignore[reportPrivateUsage]
        '```json\n{"matches": [{"name": "X", "confidence": 0.5}]}\n```'
    )
    assert matches == [{"name": "X", "title": None, "linkedin_url": None, "confidence": 0.5}]


def test_unit__step_4__parse_response_handles_missing_confidence() -> None:
    matches = step_4_web_fallback._parse_response(  # pyright: ignore[reportPrivateUsage]
        '{"matches": [{"name": "X"}]}'
    )
    # Default confidence 0.5 applied.
    assert len(matches) == 1
    assert matches[0]["confidence"] == 0.5
