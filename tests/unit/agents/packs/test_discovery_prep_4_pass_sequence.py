"""M11 — verify the 4-pass sequence + tool binding + persistence call.

``Agent.invoke`` is mocked so no real Anthropic call fires. Each pass returns a
pre-canned ``AgentResult`` so we can assert the orchestration sequence + the
shape of the payload handed to the persistence service.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.agents.bundles import ContextBundle, ContextBundleMetadata
from app.agents.packs.discovery_prep import DiscoveryPrepPackAgent
from app.agents.results import AgentResult, AgentTelemetry

_AGENCY_ID = UUID(int=0)


def _ar(
    *,
    text: str = "ok",
    structured: dict[str, Any] | None = None,
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_read: int = 0,
) -> AgentResult:
    return AgentResult(
        output_text=text,
        structured_output=structured,
        telemetry=AgentTelemetry(
            model="claude-opus-4-7",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
            cost_usd=Decimal("0.10"),
            latency_ms=1234,
        ),
    )


def _bundle() -> ContextBundle:
    return ContextBundle(
        metadata=ContextBundleMetadata(
            pack_type="discovery_prep",
            deal_id="deal_pipeline_x",
            agency_id=_AGENCY_ID,
            assembled_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        ),
        talent_profile={"talent_id": "t_riley", "name": "Riley"},
        agency_profile={"agency_id": "a_x", "name": "Acme"},
        deal_record={"deal_id": "deal_pipeline_x", "stage": "lead"},
        brand_record={"brand_id": "b_lulu", "name": "Lululemon"},
        brand_contact={"contact_id": "bc_a", "name": "Alice"},
        comparable_brand_deals=[{"brand_deal_id": "bd_1"}],
        top_pitch_angles=[{"angle_id": "ang_1"}],
    )


_BRIEFING = {
    "deal_summary": "...",
    "about_brand": "...",
    "about_contact": "...",
    "about_talent_for_call": "...",
    "fit_hypothesis": "...",
    "likely_objections": [{"objection": "Pricing", "response": "Anchor"}],
    "red_flags": ["timing"],
    "questions_to_ask": ["What's the brief?"],
    "questions_from_them": [],
    "commercial_range": "$45-65k",
}
_AGENDA = {
    "duration_total_min": 45,
    "sections": [
        {
            "title": "Introductions",
            "duration_min": 2,
            "purpose": "Warm up.",
            "talking_points": ["Hi"],
        }
    ],
}
_SLIDES = {
    "slides": [
        {
            "slide_id": "s1",
            "position": 1,
            "title": "Intro",
            "type": "intro",
            "live_body": "Hello",
            "leave_behind_extension": "...",
            "speaker_notes": "...",
            "sources": [{"url": "https://example.com", "title": "src"}],
        }
    ]
}


def _mock_persistence_result(prep_pack_id: str = "prep_test_v1") -> MagicMock:
    """Stand-in for PrepPackPersistResult — only needs the .prep_pack accessor."""
    pack = MagicMock()
    pack.prep_pack_id = prep_pack_id
    pack.version = 1
    result = MagicMock()
    result.prep_pack = pack
    result.artefact_paths = {
        "briefing-notes.md": "/tmp/briefing.md",
        "agenda.md": "/tmp/agenda.md",
        "slides.md": "/tmp/slides.md",
        "speaker-notes.md": "/tmp/speaker.md",
        "v1.json": "/tmp/v1.json",
    }
    return result


@pytest.mark.asyncio
async def test_unit__4pass__sequence_and_tool_binding() -> None:
    """All 4 passes fire in order, with the right tools bound per pass."""
    session = MagicMock()
    agent = DiscoveryPrepPackAgent(session, agency_id=_AGENCY_ID)
    invocations: list[dict[str, Any]] = []

    async def _fake_invoke(
        self: Any, prompt: str, *, cache_control_prefix: str | None = None
    ) -> AgentResult:
        invocations.append(
            {
                "agent_name": self.agent_name,
                "tools": dict(getattr(self, "tools", {})),
                "has_cache_prefix": cache_control_prefix is not None,
            }
        )
        if self.agent_name == "researcher":
            return _ar(text="research findings + URLs")
        if self.agent_name == "writer-briefing":
            return _ar(text="", structured=_BRIEFING, cache_read=80)
        if self.agent_name == "writer-agenda":
            return _ar(text="", structured=_AGENDA, cache_read=80)
        if self.agent_name == "writer-slides":
            return _ar(text="", structured=_SLIDES, cache_read=80)
        raise AssertionError(f"unexpected agent_name {self.agent_name}")

    with (
        patch("app.agents.base.Agent.invoke", _fake_invoke),
        patch(
            "app.agents.packs.discovery_prep.persist_prep_pack",
            AsyncMock(return_value=_mock_persistence_result()),
        ),
    ):
        results = await agent._run_passes(_bundle())  # pyright: ignore[reportPrivateUsage]

    # Sequence: research -> briefing -> agenda -> slides.
    assert [inv["agent_name"] for inv in invocations] == [
        "researcher",
        "writer-briefing",
        "writer-agenda",
        "writer-slides",
    ]
    # Every pass got the static cache prefix.
    assert all(inv["has_cache_prefix"] for inv in invocations)
    # Tool binding: researcher = memo + exa; briefing/agenda = none; slides = memo only.
    research_tools = set(invocations[0]["tools"])
    assert research_tools == {"read_memos", "write_memo", "exa_search", "exa_get_contents"}
    assert invocations[1]["tools"] == {}
    assert invocations[2]["tools"] == {}
    assert set(invocations[3]["tools"]) == {"read_memos", "write_memo"}
    # 4 results returned.
    assert set(results.keys()) == {"research", "briefing", "agenda", "slides"}


@pytest.mark.asyncio
async def test_unit__4pass__failed_pass_raises_business_rule_error() -> None:
    session = MagicMock()
    agent = DiscoveryPrepPackAgent(session, agency_id=_AGENCY_ID)

    async def _fake_invoke(
        self: Any, prompt: str, *, cache_control_prefix: str | None = None
    ) -> AgentResult:
        if self.agent_name == "researcher":
            return AgentResult(
                output_text=None,
                telemetry=AgentTelemetry(model="claude-opus-4-7"),
                error_code="VALIDATION_ERROR",
                error_message="researcher kaput",
            )
        raise AssertionError("should not reach later passes")

    from app.errors import BusinessRuleError

    with (
        patch("app.agents.base.Agent.invoke", _fake_invoke),
        patch(
            "app.agents.packs.discovery_prep.persist_prep_pack",
            AsyncMock(return_value=_mock_persistence_result()),
        ),
        pytest.raises(BusinessRuleError, match=r"researcher kaput|Researcher pass failed"),
    ):
        await agent._run_passes(_bundle())  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_unit__4pass__persists_with_assembled_payload() -> None:
    """The persistence service receives a payload matching the schema shape."""
    session = MagicMock()
    agent = DiscoveryPrepPackAgent(
        session,
        agency_id=_AGENCY_ID,
        pre_generation_guidance="Lead with the Lululemon case study",
    )

    captured_kwargs: dict[str, Any] = {}

    async def _fake_invoke(
        self: Any, prompt: str, *, cache_control_prefix: str | None = None
    ) -> AgentResult:
        if self.agent_name == "researcher":
            return _ar(text="research summary")
        if self.agent_name == "writer-briefing":
            return _ar(structured=_BRIEFING, cache_read=80)
        if self.agent_name == "writer-agenda":
            return _ar(structured=_AGENDA, cache_read=80)
        if self.agent_name == "writer-slides":
            return _ar(structured=_SLIDES, cache_read=80)
        raise AssertionError

    async def _fake_persist(*_args: Any, **kwargs: Any) -> MagicMock:
        captured_kwargs.update(kwargs)
        return _mock_persistence_result()

    with (
        patch("app.agents.base.Agent.invoke", _fake_invoke),
        patch("app.agents.packs.discovery_prep.persist_prep_pack", _fake_persist),
    ):
        await agent._run_passes(_bundle())  # pyright: ignore[reportPrivateUsage]

    assert captured_kwargs["deal_id"] == "deal_pipeline_x"
    assert captured_kwargs["version"] == 1
    assert captured_kwargs["parent_version"] is None
    payload = captured_kwargs["pack_payload"]
    assert payload["briefing_notes"] == _BRIEFING
    assert payload["agenda"] == _AGENDA
    assert payload["slides"] == _SLIDES["slides"]
    assert payload["generation"]["llm_model"] == "claude-opus-4-7"
    assert payload["generation"]["pre_generation_guidance"] == "Lead with the Lululemon case study"
    assert payload["generation"]["trigger"] == "auto_on_initial_call_scheduled"
    assert len(payload["generation"]["llm_passes"]) == 4
    # Artefacts contain rendered markdown for each deliverable.
    artefacts = captured_kwargs["artefacts"]
    assert "Briefing Notes" in artefacts.briefing_notes_md
    assert "Agenda" in artefacts.agenda_md
    assert "Slides" in artefacts.slides_md
    assert "Speaker Notes" in artefacts.speaker_notes_md


@pytest.mark.asyncio
async def test_unit__4pass__regen_threads_parent_version_and_feedback() -> None:
    """v2 regen: parent_version=1 + regen feedback flows into the payload."""
    session = MagicMock()
    agent = DiscoveryPrepPackAgent(
        session,
        agency_id=_AGENCY_ID,
        regeneration_feedback="Drop the sustainability angle",
        parent_version=1,
    )

    captured_kwargs: dict[str, Any] = {}

    async def _fake_invoke(
        self: Any, prompt: str, *, cache_control_prefix: str | None = None
    ) -> AgentResult:
        if self.agent_name == "researcher":
            return _ar(text="research summary v2")
        if self.agent_name == "writer-briefing":
            return _ar(structured=_BRIEFING)
        if self.agent_name == "writer-agenda":
            return _ar(structured=_AGENDA)
        if self.agent_name == "writer-slides":
            return _ar(structured=_SLIDES)
        raise AssertionError

    async def _fake_persist(*_args: Any, **kwargs: Any) -> MagicMock:
        captured_kwargs.update(kwargs)
        return _mock_persistence_result(prep_pack_id="prep_x_v2")

    with (
        patch("app.agents.base.Agent.invoke", _fake_invoke),
        patch("app.agents.packs.discovery_prep.persist_prep_pack", _fake_persist),
    ):
        await agent._run_passes(_bundle())  # pyright: ignore[reportPrivateUsage]

    assert captured_kwargs["version"] == 2
    assert captured_kwargs["parent_version"] == 1
    assert captured_kwargs["pack_payload"]["generation"]["trigger"] == "agent_full_regenerate"
    assert (
        captured_kwargs["pack_payload"]["generation"]["regeneration_feedback"]
        == "Drop the sustainability angle"
    )
