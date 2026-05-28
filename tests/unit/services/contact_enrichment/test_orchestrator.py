"""Orchestrator — full 9-step fan-out + error rollup."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.contact_enrichment import orchestrator


def _apollo_person(
    *,
    apollo_id: str,
    name: str,
    title: str = "VP Marketing",
    seniority: str = "vp",
    email: str | None = "x@brand.com",
    email_status: str = "verified",
    linkedin_url: str | None = "https://l/x",
) -> dict[str, Any]:
    return {
        "id": apollo_id,
        "name": name,
        "title": title,
        "seniority": seniority,
        "email": email,
        "email_status": email_status,
        "linkedin_url": linkedin_url,
    }


def _llm_response(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


@pytest.mark.asyncio
async def test_unit__orchestrator__missing_domain_returns_early_with_error() -> None:
    result = await orchestrator.run_enrichment(
        brand_id="gymshark",
        brand_metadata={"name": "Gymshark"},  # no domain
    )
    assert result.contacts == []
    assert result.blocked == []
    assert any("domain" in e for e in result.errors)
    assert result.steps_run == []


@pytest.mark.asyncio
async def test_unit__orchestrator__happy_path_runs_all_steps() -> None:
    apollo = MagicMock()
    apollo.search_people = AsyncMock(
        return_value={
            "people": [_apollo_person(apollo_id="ap_1", name="Alice", title="VP Marketing")]
        }
    )
    linkedin = MagicMock()
    linkedin.get_profile_by_url = AsyncMock(return_value={"headline": "VP Marketing"})

    llm = MagicMock()
    llm.messages.create = AsyncMock(
        return_value=_llm_response(
            '{"classifications": [{"contact_id": "bc_gymshark_ap_1", '
            '"decision_role": "buyer", "rationale": "VP at growth-stage brand"}]}'
        )
    )

    exa = MagicMock()
    exa.search = AsyncMock(return_value={"results": []})

    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=llm),
    ):
        result = await orchestrator.run_enrichment(
            brand_id="gymshark",
            brand_metadata={"name": "Gymshark", "domain": "gymshark.com"},
            target_titles=["VP Marketing"],
            apollo_client=apollo,
            linkedin_client=linkedin,
        )

    assert result.brand_id == "gymshark"
    assert "step_2_apollo_search" in result.steps_run
    assert "step_3_linkedin_enrich" in result.steps_run
    assert "step_4_web_fallback" in result.steps_run
    assert "step_5_email_verify" in result.steps_run
    assert "step_6_decision_role" in result.steps_run
    assert "step_8_dedupe_merge" in result.steps_run
    assert len(result.contacts) == 1
    assert result.contacts[0].contact.decision_role == "buyer"


@pytest.mark.asyncio
async def test_unit__orchestrator__apollo_failure_recorded_but_continues() -> None:
    apollo = MagicMock()
    apollo.search_people = AsyncMock(side_effect=RuntimeError("Apollo down"))
    # Even with Apollo down, Step 4 (Exa) and Step 5 still run.
    exa = MagicMock()
    exa.search = AsyncMock(return_value={"results": []})
    llm = MagicMock()

    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=llm),
    ):
        result = await orchestrator.run_enrichment(
            brand_id="gymshark",
            brand_metadata={"name": "Gymshark", "domain": "gymshark.com"},
            target_titles=["VP Marketing"],
            apollo_client=apollo,
        )

    # Apollo is fail-soft per-title, so Step 2 still appears in steps_run
    # (it didn't crash the orchestrator); errors list stays empty.
    assert "step_2_apollo_search" in result.steps_run
    assert "step_5_email_verify" in result.steps_run


@pytest.mark.asyncio
async def test_unit__orchestrator__qualification_threshold_drops_contacts() -> None:
    apollo = MagicMock()
    # Surface a junior contact who won't clear the 0.30 threshold.
    apollo.search_people = AsyncMock(
        return_value={
            "people": [
                {
                    "id": "ap_1",
                    "name": "Junior Jo",
                    "title": "Operations Coordinator",
                    "seniority": "ic",
                }
            ]
        }
    )
    exa = MagicMock()
    exa.search = AsyncMock(return_value={"results": []})
    llm = MagicMock()
    llm.messages.create = AsyncMock(return_value=_llm_response('{"classifications": []}'))
    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=llm),
    ):
        result = await orchestrator.run_enrichment(
            brand_id="gymshark",
            brand_metadata={"name": "Gymshark", "domain": "gymshark.com"},
            target_titles=["Operations"],
            apollo_client=apollo,
            linkedin_client=MagicMock(),
        )
    assert result.contacts == []
    assert len(result.blocked) == 1  # qualification threshold blocked them


@pytest.mark.asyncio
async def test_unit__orchestrator__dnc_in_existing_workflow_blocks() -> None:
    apollo = MagicMock()
    apollo.search_people = AsyncMock(
        return_value={
            "people": [_apollo_person(apollo_id="ap_1", name="Alice", title="VP Marketing")]
        }
    )
    exa = MagicMock()
    exa.search = AsyncMock(return_value={"results": []})
    llm = MagicMock()
    llm.messages.create = AsyncMock(
        return_value=_llm_response(
            '{"classifications": [{"contact_id": "bc_gymshark_ap_1", '
            '"decision_role": "buyer", "rationale": "x"}]}'
        )
    )
    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=llm),
    ):
        result = await orchestrator.run_enrichment(
            brand_id="gymshark",
            brand_metadata={"name": "Gymshark", "domain": "gymshark.com"},
            target_titles=["VP Marketing"],
            apollo_client=apollo,
            linkedin_client=MagicMock(),
            existing_workflow={"bc_gymshark_ap_1": {"do_not_contact": True}},
        )
    assert result.contacts == []
    assert len(result.blocked) == 1
