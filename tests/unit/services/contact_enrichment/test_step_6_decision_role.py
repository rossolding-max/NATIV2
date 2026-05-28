"""Step 6 — Claude decision_role classifier."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.contact_enrichment import step_6_decision_role
from app.services.contact_enrichment._models import EnrichedContact


def _llm_response(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


def _contact(contact_id: str, title: str = "VP Marketing") -> EnrichedContact:
    return EnrichedContact(
        contact_id=contact_id,
        brand_id="gymshark",
        name="X",
        title=title,
        seniority="vp",
    )


@pytest.mark.asyncio
async def test_unit__step_6__classifies_each_contact() -> None:
    response = _llm_response(
        '{"classifications": ['
        '{"contact_id": "bc_1", "decision_role": "buyer", "rationale": "founder"},'
        '{"contact_id": "bc_2", "decision_role": "influencer", "rationale": "manager"}'
        "]}"
    )
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    contacts = [_contact("bc_1"), _contact("bc_2")]
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        out = await step_6_decision_role.run(contacts=contacts, brand_metadata={"name": "G"})
    by_id = {c.contact_id: c for c in out}
    assert by_id["bc_1"].decision_role == "buyer"
    assert by_id["bc_2"].decision_role == "influencer"
    assert by_id["bc_1"].decision_role_rationale == "founder"


@pytest.mark.asyncio
async def test_unit__step_6__invalid_role_falls_back_to_unknown() -> None:
    response = _llm_response(
        '{"classifications": [{"contact_id": "bc_1", '
        '"decision_role": "decision_maker", "rationale": "x"}]}'
    )
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        out = await step_6_decision_role.run(
            contacts=[_contact("bc_1")], brand_metadata={"name": "G"}
        )
    assert out[0].decision_role == "unknown"


@pytest.mark.asyncio
async def test_unit__step_6__llm_exception_leaves_unknown() -> None:
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=RuntimeError("LLM down"))
    contacts = [_contact("bc_1"), _contact("bc_2")]
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        out = await step_6_decision_role.run(contacts=contacts, brand_metadata={"name": "G"})
    assert all(c.decision_role == "unknown" for c in out)


@pytest.mark.asyncio
async def test_unit__step_6__missing_contact_id_in_response_leaves_unknown() -> None:
    """LLM only classifies bc_1; bc_2 unaddressed → stays default 'unknown'."""
    response = _llm_response(
        '{"classifications": [{"contact_id": "bc_1", "decision_role": "buyer", "rationale": "x"}]}'
    )
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    contacts = [_contact("bc_1"), _contact("bc_2")]
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        out = await step_6_decision_role.run(contacts=contacts, brand_metadata={"name": "G"})
    by_id = {c.contact_id: c for c in out}
    assert by_id["bc_1"].decision_role == "buyer"
    assert by_id["bc_2"].decision_role == "unknown"


@pytest.mark.asyncio
async def test_unit__step_6__empty_contact_list_no_llm_call() -> None:
    client = MagicMock()
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        out = await step_6_decision_role.run(contacts=[], brand_metadata={"name": "G"})
    assert out == []
    client.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_unit__step_6__code_fenced_response_parsed() -> None:
    response = _llm_response(
        '```json\n{"classifications": [{"contact_id": "bc_1", '
        '"decision_role": "champion", "rationale": "x"}]}\n```'
    )
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        out = await step_6_decision_role.run(
            contacts=[_contact("bc_1")], brand_metadata={"name": "G"}
        )
    assert out[0].decision_role == "champion"


@pytest.mark.asyncio
async def test_unit__step_6__prompt_includes_brand_metadata() -> None:
    captured: dict[str, Any] = {}

    async def _capture(**kwargs: Any) -> Any:
        captured["prompt"] = kwargs["messages"][0]["content"]
        return _llm_response('{"classifications": []}')

    client = MagicMock()
    client.messages.create = _capture
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        await step_6_decision_role.run(
            contacts=[_contact("bc_1")],
            brand_metadata={
                "name": "Gymshark",
                "typical_campaign_tier": "premium",
                "company_stage": "growth",
            },
        )
    prompt = captured["prompt"]
    assert "Gymshark" in prompt
    assert "premium" in prompt
    assert "growth" in prompt
