"""Reply classifier — 7 outcomes + extracted signals + fail-soft."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.outreach import reply_classifier


def _llm_response(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    r = MagicMock()
    r.content = [block]
    return r


@pytest.mark.asyncio
async def test_unit__classifier__interested_with_meeting_signal() -> None:
    response = _llm_response(
        '{"outcome": "interested", "confidence": 0.92, '
        '"rationale": "Asked for a call next week", '
        '"extracted_signals": {"asked_for_meeting": true, '
        '"asked_for_pricing": false, "asked_for_more_info": false, '
        '"objections_raised": [], "next_step_proposed": "call next week", '
        '"ooo_until": null, "routed_to_contact": null}}'
    )
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        out = await reply_classifier.classify_reply(reply_body="Sounds great, free Tuesday?")
    assert out.outcome == "interested"
    assert out.confidence == 0.92
    assert out.extracted_signals["asked_for_meeting"] is True


@pytest.mark.asyncio
async def test_unit__classifier__unknown_outcome_falls_back_to_needs_more_info() -> None:
    response = _llm_response(
        '{"outcome": "very_interested", "confidence": 0.9, '
        '"rationale": "x", "extracted_signals": {}}'
    )
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        out = await reply_classifier.classify_reply(reply_body="...")
    assert out.outcome == "needs_more_info"


@pytest.mark.asyncio
async def test_unit__classifier__llm_error_failsoft() -> None:
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=RuntimeError("down"))
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        out = await reply_classifier.classify_reply(reply_body="...")
    assert out.outcome == "needs_more_info"
    assert out.confidence == 0.0
    assert "llm_error" in out.rationale


@pytest.mark.asyncio
async def test_unit__classifier__malformed_json_failsoft() -> None:
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_llm_response("not json at all"))
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        out = await reply_classifier.classify_reply(reply_body="...")
    assert out.outcome == "needs_more_info"
    assert out.rationale == "unparseable_json"


@pytest.mark.asyncio
async def test_unit__classifier__confidence_clamped_to_unit_interval() -> None:
    response = _llm_response(
        '{"outcome": "declined", "confidence": 1.5, "rationale": "x", "extracted_signals": {}}'
    )
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        out = await reply_classifier.classify_reply(reply_body="...")
    assert out.confidence == 1.0


@pytest.mark.asyncio
async def test_unit__classifier__out_of_office_extracts_until_date() -> None:
    response = _llm_response(
        '{"outcome": "out_of_office", "confidence": 0.95, '
        '"rationale": "OOO until 2026-06-15", '
        '"extracted_signals": {"ooo_until": "2026-06-15"}}'
    )
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        out = await reply_classifier.classify_reply(reply_body="OOO until June 15")
    assert out.outcome == "out_of_office"
    assert out.extracted_signals["ooo_until"] == "2026-06-15"
