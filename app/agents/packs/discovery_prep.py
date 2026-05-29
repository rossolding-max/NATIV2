"""``DiscoveryPrepPackAgent`` — Phase 4.5 discovery prep pack coordinator.

M11 implementation of the first AI pack. Per ``docs/discovery_prep_workflow.md``:

- Pass 0: researcher subagent runs 3-5 Exa queries + reads memos + writes
  one ``brand_observation`` memo capturing new learnings.
- Pass 1: writer subagent drafts the structured ``briefing_notes`` (deal
  summary, brand/contact/talent profiles, fit hypothesis, likely
  objections, questions, commercial range).
- Pass 2: writer subagent drafts the ``agenda`` (6 sections, each with
  duration + talking_points), conditioned on the briefing from pass 1.
- Pass 3: writer subagent drafts the ``slides[]`` array (live + leave-behind
  bodies + speaker notes + sources), conditioned on briefing + agenda.
  This writer ALSO writes one ``talent_pattern`` memo capturing
  "how this talent should be positioned for this brand call".

Static prefix (talent + agency + brand + deal) is cached across passes
via Anthropic's ``cache_control: ephemeral`` markup so passes 1-3 hit
the prompt cache.

Persistence is atomic via ``app.services.prep_pack_persistence``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.bundles import ContextBundle
from app.agents.coordinator import DealOrchestratorAgent
from app.agents.results import AgentResult, PackResult
from app.agents.tools.exa_tools import bind_exa_tools
from app.agents.tools.memo_tools import bind_memo_tools
from app.config import settings
from app.errors import BusinessRuleError
from app.services.prep_pack_persistence import (
    PrepPackArtefacts,
    PrepPackPersistResult,
    persist_prep_pack,
)
from app.utils.logging import get_logger

log = get_logger(__name__)


class DiscoveryPrepPackAgent(DealOrchestratorAgent):
    """4-pass discovery prep pack coordinator with persistence + memo writes."""

    pack_type = "discovery_prep"

    def __init__(
        self,
        session: AsyncSession,
        *,
        agency_id: UUID,
        agent_id: str = "deal_orchestrator",
        pre_generation_guidance: str | None = None,
        regeneration_feedback: str | None = None,
        parent_version: int | None = None,
    ) -> None:
        super().__init__(session, agency_id=agency_id, agent_id=agent_id)
        self._pre_guidance = pre_generation_guidance
        self._regen_feedback = regeneration_feedback
        self._parent_version = parent_version
        self._persistence: PrepPackPersistResult | None = None

    # ── Generation knobs threaded into the bundle ────────────────────

    async def _compose_bundle(self, deal_id: str) -> ContextBundle:
        bundle = await super()._compose_bundle(deal_id)
        bundle.pre_generation_guidance = self._pre_guidance
        bundle.regeneration_feedback = self._regen_feedback
        bundle.parent_version = self._parent_version
        return bundle

    # ── 4-pass body ──────────────────────────────────────────────────

    async def _run_passes(self, bundle: ContextBundle) -> dict[str, AgentResult]:
        from app.agents.skills import ResearcherAgent, WriterAgent

        results: dict[str, AgentResult] = {}
        static_prefix = bundle.static_prefix_text()
        dynamic_body = bundle.dynamic_body_text()
        model = settings.discovery_prep_model

        # Pass 0 — researcher (Exa + memos).
        researcher = ResearcherAgent(agent_name="researcher")
        # Override the ClassVar at instance level so each subagent invocation
        # gets the model + tools the coordinator chose. Python allows this;
        # pyright flags it because ClassVar disallows instance writes.
        object.__setattr__(researcher, "model", model)
        object.__setattr__(
            researcher,
            "tools",
            {
                **bind_memo_tools(self._session, self._agency_id, created_by_agent="researcher"),
                **bind_exa_tools(agent_name="researcher"),
            },
        )
        research_result = await researcher.invoke(
            prompt=_researcher_prompt(dynamic_body, bundle),
            cache_control_prefix=static_prefix,
        )
        results["research"] = research_result
        if research_result.error_code:
            raise BusinessRuleError(
                f"Researcher pass failed: {research_result.error_message}",
                detail={"pass": "research"},
            )

        research_text = research_result.output_text or ""

        # Pass 1 — writer / briefing.
        briefing_writer = WriterAgent(agent_name="writer-briefing")
        object.__setattr__(briefing_writer, "model", model)
        object.__setattr__(briefing_writer, "tools", {})
        briefing_result = await briefing_writer.invoke(
            prompt=_briefing_prompt(dynamic_body, research_text, bundle),
            cache_control_prefix=static_prefix,
        )
        results["briefing"] = briefing_result
        if briefing_result.error_code:
            raise BusinessRuleError(
                f"Briefing pass failed: {briefing_result.error_message}",
                detail={"pass": "briefing"},
            )
        briefing_json: dict[str, Any] = briefing_result.structured_output or {}

        # Pass 2 — writer / agenda.
        agenda_writer = WriterAgent(agent_name="writer-agenda")
        object.__setattr__(agenda_writer, "model", model)
        object.__setattr__(agenda_writer, "tools", {})
        agenda_result = await agenda_writer.invoke(
            prompt=_agenda_prompt(dynamic_body, briefing_json),
            cache_control_prefix=static_prefix,
        )
        results["agenda"] = agenda_result
        if agenda_result.error_code:
            raise BusinessRuleError(
                f"Agenda pass failed: {agenda_result.error_message}",
                detail={"pass": "agenda"},
            )
        agenda_json: dict[str, Any] = agenda_result.structured_output or {}

        # Pass 3 — writer / slides (writes the closing talent_pattern memo).
        slides_writer = WriterAgent(agent_name="writer-slides")
        object.__setattr__(slides_writer, "model", model)
        object.__setattr__(
            slides_writer,
            "tools",
            bind_memo_tools(self._session, self._agency_id, created_by_agent="writer"),
        )
        slides_result = await slides_writer.invoke(
            prompt=_slides_prompt(dynamic_body, briefing_json, agenda_json),
            cache_control_prefix=static_prefix,
        )
        results["slides"] = slides_result
        if slides_result.error_code:
            raise BusinessRuleError(
                f"Slides pass failed: {slides_result.error_message}",
                detail={"pass": "slides"},
            )
        slides_json: dict[str, Any] = slides_result.structured_output or {}

        # Assemble + persist.
        version = (self._parent_version or 0) + 1
        prep_pack_id = _build_prep_pack_id(bundle.metadata.deal_id, version)
        pack_payload = _assemble_pack_payload(
            bundle=bundle,
            prep_pack_id=prep_pack_id,
            version=version,
            parent_version=self._parent_version,
            briefing=briefing_json,
            agenda=agenda_json,
            slides=slides_json,
            research_result=research_result,
            briefing_result=briefing_result,
            agenda_result=agenda_result,
            slides_result=slides_result,
            agent_id=self._agent_id,
            llm_model=model,
            pre_generation_guidance=self._pre_guidance,
            regeneration_feedback=self._regen_feedback,
        )
        artefacts = PrepPackArtefacts(
            briefing_notes_md=_render_briefing_md(briefing_json),
            agenda_md=_render_agenda_md(agenda_json),
            slides_md=_render_slides_md(slides_json),
            speaker_notes_md=_render_speaker_notes_md(slides_json),
        )
        self._persistence = await persist_prep_pack(
            self._session,
            deal_id=bundle.metadata.deal_id,
            agency_id=self._agency_id,
            prep_pack_id=prep_pack_id,
            version=version,
            parent_version=self._parent_version,
            pack_payload=pack_payload,
            artefacts=artefacts,
        )

        return results

    # ── Override run to surface persisted pack_id + artefact paths ───

    async def run(self, deal_id: str) -> PackResult[dict[str, Any]]:
        result = await super().run(deal_id)
        if result.status == "completed" and self._persistence is not None:
            return result.model_copy(
                update={
                    "pack_id": self._persistence.prep_pack.prep_pack_id,
                    "version": self._persistence.prep_pack.version,
                    "artifacts": self._persistence.artefact_paths,
                }
            )
        return result


# ── Prompt builders ─────────────────────────────────────────────────


def _researcher_prompt(dynamic_body: str, bundle: ContextBundle) -> str:
    guidance = (
        f"\nAGENT PRE-GENERATION GUIDANCE: {bundle.pre_generation_guidance}\n"
        if bundle.pre_generation_guidance
        else ""
    )
    return (
        "You are researching a discovery call for a talent x brand deal.\n"
        "\n"
        "1. Call read_memos with the brand_id + industry_id from the dynamic\n"
        "   context to surface prior learnings.\n"
        "2. Run 3-5 exa_search queries: recent brand campaigns + brand news +\n"
        "   contact background (if name + title surface) + competitor landscape.\n"
        "3. Write one brand_observation memo summarising the NEW campaign /\n"
        "   cultural / competitor learnings (scope=brand_relationship, tags must\n"
        "   include brand_ids + topics).\n"
        "4. Reply with a short textual summary of the most relevant findings\n"
        "   (URLs MUST be preserved verbatim for the slide deck's sources).\n"
        f"{guidance}\n"
        "Dynamic context follows.\n\n"
        f"{dynamic_body}"
    )


def _briefing_prompt(dynamic_body: str, research_text: str, bundle: ContextBundle) -> str:
    regen_block = (
        f"\nREGEN FEEDBACK (apply to v{(bundle.parent_version or 0) + 1}): "
        f"{bundle.regeneration_feedback}\n"
        if bundle.regeneration_feedback
        else ""
    )
    return (
        "Draft the structured briefing_notes for the discovery call.\n"
        "Return ONLY a JSON object matching:\n"
        "{\n"
        '  "deal_summary": str,\n'
        '  "about_brand": str,\n'
        '  "about_contact": str,\n'
        '  "about_talent_for_call": str,\n'
        '  "fit_hypothesis": str,\n'
        '  "likely_objections": [{"objection": str, "response": str}],\n'
        '  "red_flags": [str],\n'
        '  "questions_to_ask": [str],\n'
        '  "questions_from_them": [{"question": str, "prepared_answer": str}],\n'
        '  "commercial_range": str\n'
        "}\n"
        f"{regen_block}\n"
        "Research output to ground your briefing:\n"
        f"{research_text}\n\n"
        "Dynamic context follows.\n\n"
        f"{dynamic_body}"
    )


def _agenda_prompt(dynamic_body: str, briefing: dict[str, Any]) -> str:
    import json as _json

    return (
        "Draft the agenda for the discovery call (default 45 min total).\n"
        "Return ONLY a JSON object:\n"
        "{\n"
        '  "duration_total_min": int,\n'
        '  "sections": [\n'
        '    {"title": str, "duration_min": int, "purpose": str,\n'
        '     "talking_points": [str]}\n'
        "  ]\n"
        "}\n"
        "Sections: introductions / brand overview / talent overview / objectives\n"
        "/ opportunities / next steps. Use SPICED internally to phrase the\n"
        "objectives talking_points as questions (situation, pain, impact,\n"
        "critical event, decision).\n\n"
        "Briefing (from pass 1):\n"
        f"{_json.dumps(briefing, default=str)[:6000]}\n\n"
        "Dynamic context follows.\n\n"
        f"{dynamic_body}"
    )


def _slides_prompt(dynamic_body: str, briefing: dict[str, Any], agenda: dict[str, Any]) -> str:
    import json as _json

    return (
        "Draft the slide deck JSON for the discovery call. Live deck (what's\n"
        "shown on screen) + leave-behind extension (full version sent after).\n"
        "Return ONLY a JSON object:\n"
        "{\n"
        '  "slides": [\n'
        '    {"slide_id": str, "position": int, "title": str,\n'
        '     "type": "intro|brand|talent|opportunity|cta",\n'
        '     "live_body": str, "leave_behind_extension": str,\n'
        '     "speaker_notes": str,\n'
        '     "sources": [{"url": str, "title": str}]}\n'
        "  ]\n"
        "}\n"
        "After producing the JSON, call write_memo to store one\n"
        "talent_pattern memo (scope=talent_pattern, tags.talent_ids=[talent_id])\n"
        "capturing how this talent should be positioned for this brand call.\n\n"
        "Briefing:\n"
        f"{_json.dumps(briefing, default=str)[:4000]}\n\n"
        "Agenda:\n"
        f"{_json.dumps(agenda, default=str)[:2000]}\n\n"
        "Dynamic context follows.\n\n"
        f"{dynamic_body}"
    )


# ── Pack-payload assembly ────────────────────────────────────────────


def _build_prep_pack_id(_deal_id: str, version: int) -> str:
    """Schema pattern: ``^prep_[a-z0-9_-]+_v[0-9]+$``.

    We don't fold the full deal_id into the id (it can be 80 chars + may
    collide with the pattern); a uuid suffix keeps it short + globally
    unique. ``_deal_id`` accepted for symmetry with the workflow doc's
    example format.
    """
    suffix = uuid4().hex[:10]
    return f"prep_{suffix}_v{version}"


def _assemble_pack_payload(
    *,
    bundle: ContextBundle,
    prep_pack_id: str,
    version: int,
    parent_version: int | None,
    briefing: dict[str, Any],
    agenda: dict[str, Any],
    slides: dict[str, Any],
    research_result: AgentResult,
    briefing_result: AgentResult,
    agenda_result: AgentResult,
    slides_result: AgentResult,
    agent_id: str,
    llm_model: str,
    pre_generation_guidance: str | None,
    regeneration_feedback: str | None,
) -> dict[str, Any]:
    """Build the JSON payload matching ``discovery_prep_pack.schema.json``."""
    now = datetime.now(UTC).isoformat()
    trigger = "agent_full_regenerate" if parent_version else "auto_on_initial_call_scheduled"
    llm_passes = [
        _pass_record("external_research", research_result),
        _pass_record("briefing", briefing_result),
        _pass_record("agenda", agenda_result),
        _pass_record("slides", slides_result),
    ]

    context_snapshot: dict[str, Any] = {
        "deal_stage_at_gen": bundle.deal_record.get("stage"),
        "talent_id": bundle.talent_profile.get("talent_id"),
        "brand_candidate_id": bundle.brand_record.get("brand_id"),
        "comparable_brand_deal_ids": [
            d.get("brand_deal_id") for d in bundle.comparable_brand_deals
        ],
        "top_scoring_angle_ids": [a.get("angle_id") for a in bundle.top_pitch_angles],
    }

    payload: dict[str, Any] = {
        "prep_pack_id": prep_pack_id,
        "deal_id": bundle.metadata.deal_id,
        "version": version,
        "is_latest": True,
        "agency_id": str(bundle.metadata.agency_id),
        "generation": {
            "trigger": trigger,
            "pre_generation_guidance": pre_generation_guidance,
            "regeneration_feedback": regeneration_feedback,
            "generated_at": now,
            "generated_by_agent_id": agent_id,
            "llm_model": llm_model,
            "llm_passes": llm_passes,
        },
        "context_snapshot": context_snapshot,
        "briefing_notes": briefing,
        "agenda": agenda,
        "slides": slides.get("slides") or [],
        "created_at": now,
    }
    if parent_version is not None:
        payload["parent_version"] = parent_version
    return payload


def _pass_record(name: str, result: AgentResult) -> dict[str, Any]:
    return {
        "pass_name": name,
        "input_tokens": result.telemetry.input_tokens,
        "output_tokens": result.telemetry.output_tokens,
        "cache_read_input_tokens": result.telemetry.cache_read_input_tokens,
        "cache_creation_input_tokens": result.telemetry.cache_creation_input_tokens,
        "cost_usd": str(result.telemetry.cost_usd),
        "latency_ms": result.telemetry.latency_ms,
    }


# ── Markdown rendering helpers ──────────────────────────────────────


def _render_briefing_md(briefing: dict[str, Any]) -> str:
    objections = briefing.get("likely_objections") or []
    questions = briefing.get("questions_to_ask") or []
    return "\n".join(
        [
            "# Discovery Call — Briefing Notes",
            "",
            "## Deal summary",
            str(briefing.get("deal_summary") or ""),
            "",
            "## About the brand",
            str(briefing.get("about_brand") or ""),
            "",
            "## About the contact",
            str(briefing.get("about_contact") or ""),
            "",
            "## About the talent (for this call)",
            str(briefing.get("about_talent_for_call") or ""),
            "",
            "## Fit hypothesis",
            str(briefing.get("fit_hypothesis") or ""),
            "",
            "## Likely objections + responses",
            *(
                f"- **{o.get('objection')}** -> {o.get('response')}"
                for o in objections
                if isinstance(o, dict)
            ),
            "",
            "## Red flags",
            *(f"- {flag}" for flag in (briefing.get("red_flags") or [])),
            "",
            "## Questions to ask them",
            *(f"- {q}" for q in questions),
            "",
            "## Commercial range (internal)",
            str(briefing.get("commercial_range") or ""),
            "",
        ]
    )


def _render_agenda_md(agenda: dict[str, Any]) -> str:
    sections = agenda.get("sections") or []
    out = [
        "# Discovery Call Agenda",
        "",
        f"**Total:** {agenda.get('duration_total_min', 45)} min",
        "",
    ]
    for section in sections:
        if not isinstance(section, dict):
            continue
        out.append(f"## {section.get('title')} ({section.get('duration_min')} min)")
        out.append(str(section.get("purpose") or ""))
        out.append("")
        for tp in section.get("talking_points") or []:
            out.append(f"- {tp}")
        out.append("")
    return "\n".join(out)


def _render_slides_md(slides: dict[str, Any]) -> str:
    out = ["# Discovery Call Slides (markdown)", ""]
    for slide in slides.get("slides") or []:
        if not isinstance(slide, dict):
            continue
        out.append(f"## Slide {slide.get('position')} — {slide.get('title')}")
        out.append(f"_Type: {slide.get('type')}_")
        out.append("")
        out.append("### Live body")
        out.append(str(slide.get("live_body") or ""))
        out.append("")
        out.append("### Leave-behind extension")
        out.append(str(slide.get("leave_behind_extension") or ""))
        out.append("")
        sources = slide.get("sources") or []
        if sources:
            out.append("### Sources")
            for s in sources:
                if isinstance(s, dict):
                    out.append(f"- [{s.get('title')}]({s.get('url')})")
            out.append("")
    return "\n".join(out)


def _render_speaker_notes_md(slides: dict[str, Any]) -> str:
    out = ["# Discovery Call — Speaker Notes", ""]
    for slide in slides.get("slides") or []:
        if not isinstance(slide, dict):
            continue
        out.append(f"## Slide {slide.get('position')} — {slide.get('title')}")
        out.append(str(slide.get("speaker_notes") or ""))
        out.append("")
    return "\n".join(out)
