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


# ── M8.1 — outreach_recommendation dual-classification ────────────


@pytest.mark.asyncio
async def test_unit__step_6_m81__emits_both_classifications() -> None:
    """One LLM call returns both decision_role + outreach_recommendation."""
    response = _llm_response(
        '{"classifications": ['
        '{"contact_id": "bc_1", "decision_role": "buyer", '
        '"decision_role_rationale": "founder of a small DTC brand", '
        '"outreach_recommendation": "recommended", '
        '"outreach_recommendation_rationale": "founder of sub-200 brand, direct pitch fits"},'
        '{"contact_id": "bc_2", "decision_role": "influencer", '
        '"decision_role_rationale": "CMO at megabrand; deal sign-off below", '
        '"outreach_recommendation": "not_recommended", '
        '"outreach_recommendation_rationale": "too senior to engage directly with creator pitches"}'
        "]}"
    )
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    contacts = [
        _contact("bc_1", title="Founder"),
        _contact("bc_2", title="Chief Marketing Officer"),
    ]
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        out = await step_6_decision_role.run(contacts=contacts, brand_metadata={"name": "G"})
    by_id = {c.contact_id: c for c in out}
    assert by_id["bc_1"].decision_role == "buyer"
    assert by_id["bc_1"].outreach_recommendation == "recommended"
    assert "founder" in by_id["bc_1"].outreach_recommendation_rationale.lower()
    assert by_id["bc_2"].decision_role == "influencer"
    assert by_id["bc_2"].outreach_recommendation == "not_recommended"


@pytest.mark.asyncio
async def test_unit__step_6_m81__invalid_recommendation_falls_back_to_requires_review() -> None:
    """Unknown recommendation value never auto-promotes to recommended."""
    response = _llm_response(
        '{"classifications": [{"contact_id": "bc_1", "decision_role": "buyer", '
        '"decision_role_rationale": "x", '
        '"outreach_recommendation": "definitely_pitch_them", '
        '"outreach_recommendation_rationale": "x"}]}'
    )
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        out = await step_6_decision_role.run(
            contacts=[_contact("bc_1")], brand_metadata={"name": "G"}
        )
    assert out[0].outreach_recommendation == "requires_review"


@pytest.mark.asyncio
async def test_unit__step_6_m81__missing_recommendation_falls_back_to_requires_review() -> None:
    """Legacy single-classification response → recommendation stays default."""
    response = _llm_response(
        '{"classifications": [{"contact_id": "bc_1", "decision_role": "buyer", '
        '"rationale": "founder of small DTC"}]}'
    )
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        out = await step_6_decision_role.run(
            contacts=[_contact("bc_1")], brand_metadata={"name": "G"}
        )
    # decision_role still parses; legacy `rationale` key supported for back-compat.
    assert out[0].decision_role == "buyer"
    assert out[0].decision_role_rationale == "founder of small DTC"
    # Default — never auto-promoted when the LLM didn't supply the field.
    assert out[0].outreach_recommendation == "requires_review"
    assert out[0].outreach_recommendation_rationale == ""


@pytest.mark.asyncio
async def test_unit__step_6_m81__llm_failure_leaves_default_recommendation() -> None:
    """LLM error path: every contact has requires_review (the default)."""
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=RuntimeError("LLM down"))
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        out = await step_6_decision_role.run(
            contacts=[_contact("bc_1"), _contact("bc_2")], brand_metadata={"name": "G"}
        )
    assert all(c.outreach_recommendation == "requires_review" for c in out)


@pytest.mark.asyncio
async def test_unit__step_6_m81__prompt_documents_both_classifications() -> None:
    """The Haiku prompt mentions BOTH classification axes by name."""
    captured: dict[str, Any] = {}

    async def _capture(**kwargs: Any) -> Any:
        captured["prompt"] = kwargs["messages"][0]["content"]
        return _llm_response('{"classifications": []}')

    client = MagicMock()
    client.messages.create = _capture
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        await step_6_decision_role.run(contacts=[_contact("bc_1")], brand_metadata={"name": "X"})
    prompt = captured["prompt"]
    assert "decision_role" in prompt
    assert "outreach_recommendation" in prompt
    assert "recommended" in prompt
    assert "not_recommended" in prompt
    assert "requires_review" in prompt


def test_unit__step_6_m81__allowed_recommendations_set() -> None:
    """Sanity: the protected set covers exactly the three documented values."""
    from app.services.contact_enrichment.step_6_decision_role import (
        _ALLOWED_RECOMMENDATIONS,  # pyright: ignore[reportPrivateUsage]
    )

    assert (
        frozenset({"recommended", "not_recommended", "requires_review"}) == _ALLOWED_RECOMMENDATIONS
    )
