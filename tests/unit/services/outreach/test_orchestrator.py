"""Orchestrator — end-to-end happy + error paths with all I/O mocked."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.services.outreach import orchestrator


def _row(**kwargs: Any) -> MagicMock:
    obj = MagicMock()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj


def _talent_row() -> MagicMock:
    return _row(
        talent_id="t-1",
        name="Jane",
        data={
            "previous_brands": [{"brand": "Gymshark", "industry_id": "activewear"}],
            "content_niches": ["fitness-training"],
            "audience_demographics": {
                "top_countries": [{"country": "GB"}],
                "interests": ["fitness"],
                "gender_split": {"female": 70, "male": 30},
            },
            "similar_talent": [],
        },
    )


def _contact_row(*, decision_role: str = "buyer", do_not_contact: bool = False) -> MagicMock:
    return _row(
        contact_id="bc_x",
        brand_id="lululemon",
        name="Alice",
        decision_role=decision_role,
        email="alice@lululemon.com",
        do_not_contact=do_not_contact,
        data={"pitch_history": []},
    )


def _brand_row() -> MagicMock:
    return _row(
        brand_id="lululemon",
        name="Lululemon",
        industry_id="activewear",
        domain="lululemon.com",
        hq_country="CA",
        company_stage="public",
        typical_campaign_tier="premium",
        data={"sells_in_countries": "global"},
    )


def _template_row() -> MagicMock:
    return _row(
        template_id="buyer-direct-pitch",
        target_decision_role="buyer",
        data={
            "template_id": "buyer-direct-pitch",
            "steps": [
                {
                    "step_number": 1,
                    "intent": "first_touch_strongest_angle",
                    "timing_offset_days": 0,
                    "channel": "email",
                    "preferred_angle_categories": ["competitive_proof"],
                    "ai_model_override": "claude-haiku-4-5",
                }
            ],
            "guardrails": {
                "max_body_chars": 600,
                "max_subject_chars": 60,
                "tone": "direct_professional",
            },
        },
    )


def _angle_row() -> MagicMock:
    return _row(
        angle_id="comp_proof",
        category="competitive_proof",
        name="comp_proof",
        authored_strength_score=0.7,
        data={
            "trigger": {"type": "talent_worked_with_competitor"},
            "applicable_to_decision_roles": ["buyer"],
            "applicable_to_steps": [1],
            "merge_fields_required": [],
            "example_phrasing": "Worked with {competitor_brand}",
        },
    )


def _llm_response_text(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    r = MagicMock()
    r.content = [block]
    return r


def _make_repos() -> dict[str, MagicMock]:
    talent_repo = MagicMock()
    contact_repo = MagicMock()
    brand_repo = MagicMock()
    template_repo = MagicMock()
    angle_repo = MagicMock()
    enrollment_repo = MagicMock()

    talent_repo.get_by_talent_id = AsyncMock(return_value=_talent_row())
    contact_repo.get_by_id = AsyncMock(return_value=_contact_row())
    contact_repo.patch_workflow_state = AsyncMock()
    brand_repo.get_by_id = AsyncMock(return_value=_brand_row())
    template_repo.find_for_decision_role = AsyncMock(return_value=_template_row())
    template_repo.get_by_id = AsyncMock(return_value=_template_row())
    angle_repo.find_all = AsyncMock(return_value=[_angle_row()])
    enrollment_repo.find_active_for_contact = AsyncMock(return_value=[])
    enrollment_repo.insert_draft = AsyncMock()
    return {
        "talent_repo": talent_repo,
        "contact_repo": contact_repo,
        "brand_repo": brand_repo,
        "template_repo": template_repo,
        "angle_repo": angle_repo,
        "enrollment_repo": enrollment_repo,
    }


@pytest.mark.asyncio
async def test_unit__orchestrator__happy_path_persists_draft() -> None:
    repos = _make_repos()
    response = _llm_response_text(
        '{"subject": "Worked with Gymshark", "body": "Hi Alice, I work with Jane '
        'who has a strong track record with Gymshark...", '
        '"angles_used": {"primary": "comp_proof"}, '
        '"personalization_fields_used": ["contact.name"], "reasoning": "x"}'
    )
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)

    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        result = await orchestrator.generate_enrollment(
            talent_id="t-1",
            contact_id="bc_x",
            brand_id="lululemon",
            agency_id=UUID(int=0),
            **repos,
        )
    assert result.draft is not None
    assert result.block_reason is None
    assert len(result.draft.steps) == 1
    repos["enrollment_repo"].insert_draft.assert_awaited_once()
    repos["contact_repo"].patch_workflow_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_unit__orchestrator__dnc_contact_blocked() -> None:
    repos = _make_repos()
    repos["contact_repo"].get_by_id = AsyncMock(return_value=_contact_row(do_not_contact=True))
    result = await orchestrator.generate_enrollment(
        talent_id="t-1",
        contact_id="bc_x",
        brand_id="lululemon",
        agency_id=UUID(int=0),
        **repos,
    )
    assert result.draft is None
    assert result.block_reason == "do_not_contact"
    repos["enrollment_repo"].insert_draft.assert_not_called()


@pytest.mark.asyncio
async def test_unit__orchestrator__gatekeeper_no_template_blocks() -> None:
    repos = _make_repos()
    repos["contact_repo"].get_by_id = AsyncMock(
        return_value=_contact_row(decision_role="gatekeeper")
    )
    repos["template_repo"].find_for_decision_role = AsyncMock(return_value=None)
    result = await orchestrator.generate_enrollment(
        talent_id="t-1",
        contact_id="bc_x",
        brand_id="lululemon",
        agency_id=UUID(int=0),
        **repos,
    )
    assert result.draft is None
    assert result.block_reason is not None
    assert "no_template_for_role" in result.block_reason


@pytest.mark.asyncio
async def test_unit__orchestrator__missing_brand_blocks() -> None:
    repos = _make_repos()
    repos["brand_repo"].get_by_id = AsyncMock(return_value=None)
    result = await orchestrator.generate_enrollment(
        talent_id="t-1",
        contact_id="bc_x",
        brand_id="missing",
        agency_id=UUID(int=0),
        **repos,
    )
    assert result.draft is None
    assert result.block_reason is not None
    assert "brand" in result.block_reason


@pytest.mark.asyncio
async def test_unit__orchestrator__active_enrollment_blocks() -> None:
    """An existing active enrollment for the same talent + contact pair blocks."""
    repos = _make_repos()
    active = MagicMock()
    active.talent_id = "t-1"
    active.state = "active"
    repos["enrollment_repo"].find_active_for_contact = AsyncMock(return_value=[active])
    result = await orchestrator.generate_enrollment(
        talent_id="t-1",
        contact_id="bc_x",
        brand_id="lululemon",
        agency_id=UUID(int=0),
        **repos,
    )
    assert result.draft is None
    assert result.block_reason == "active_enrollment_for_talent"
