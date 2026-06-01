"""M7.4 — LLM industry softener (Haiku call → additional industry ids)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.discovery import _industry_softener


def _mock_tax(industries: dict[str, dict[str, Any]]) -> MagicMock:
    tax = MagicMock()
    tax.industries = industries
    return tax


def _mock_llm(response_text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = response_text
    resp = MagicMock()
    resp.content = [block]
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=resp)
    return client


@pytest.mark.asyncio
async def test_unit__softener__returns_filtered_ids_from_llm() -> None:
    tax = _mock_tax(
        {
            "toys": {"name": "Toys", "parent": None},
            "baby-care": {"name": "Baby Care", "parent": None},
            "diapers-nappies": {"name": "Diapers", "parent": "baby-care"},
        }
    )
    llm = _mock_llm(
        json.dumps(
            {
                "additional_industries": [
                    {"id": "baby-care", "rationale": "Dad-life parent niche."},
                    {"id": "diapers-nappies", "rationale": "Direct purchase intent."},
                ]
            }
        )
    )
    out = await _industry_softener.run(
        talent_data={"content_niches": ["dad-life"], "location": {"country": "US"}},
        current_industries=["toys"],
        taxonomies=tax,
        llm_client=llm,
    )
    assert set(out) == {"baby-care", "diapers-nappies"}


@pytest.mark.asyncio
async def test_unit__softener__filters_unknown_ids() -> None:
    """Ids not in the taxonomy are silently dropped."""
    tax = _mock_tax({"toys": {"name": "Toys"}})
    llm = _mock_llm(
        json.dumps(
            {
                "additional_industries": [
                    {"id": "toys", "rationale": "Already chosen"},  # dropped: in current
                    {
                        "id": "hallucinated-industry",
                        "rationale": "Hallucinated",
                    },  # dropped: not in taxonomy
                ]
            }
        )
    )
    out = await _industry_softener.run(
        talent_data={"content_niches": []},
        current_industries=["toys"],
        taxonomies=tax,
        llm_client=llm,
    )
    assert out == []


@pytest.mark.asyncio
async def test_unit__softener__empty_taxonomy_returns_empty() -> None:
    tax = _mock_tax({})
    llm = _mock_llm("{}")
    out = await _industry_softener.run(
        talent_data={},
        current_industries=[],
        taxonomies=tax,
        llm_client=llm,
    )
    assert out == []
    # LLM should not be called when taxonomy is empty.
    llm.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_unit__softener__disabled_via_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "discovery_industry_softener_enabled", False)
    tax = _mock_tax({"toys": {"name": "Toys"}})
    llm = _mock_llm(json.dumps({"additional_industries": [{"id": "toys"}]}))
    out = await _industry_softener.run(
        talent_data={},
        current_industries=[],
        taxonomies=tax,
        llm_client=llm,
    )
    assert out == []
    llm.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_unit__softener__handles_invalid_json() -> None:
    tax = _mock_tax({"toys": {"name": "Toys"}})
    llm = _mock_llm("I'm sorry, I can't comply with that.")
    out = await _industry_softener.run(
        talent_data={},
        current_industries=[],
        taxonomies=tax,
        llm_client=llm,
    )
    assert out == []
