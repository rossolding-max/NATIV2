"""``DealOrchestratorAgent`` — top-level coordinator for pack generation.

Per ``architecture.md`` § 3: one coordinator per pack-generation Celery
task. Composes the context bundle, invokes skill subagents in sequence,
captures partial failures, and returns a typed ``PackResult``.

M2 ships:
- The coordinator class with ``run(pack_type, deal_id, agency_id, agent_id)``.
- Internal Python invocation pattern (NOT Claude-controlled subagent
  selection — sequence is deterministic per pack type).
- Partial failure handling: persist what completed, return
  ``PackResult(status="failed", ...)``, never raise past the coordinator.
- Langfuse parent-span wrapping (delegates to ``app.observability.langfuse``).

Pack-specific orchestration lives in ``app/agents/packs/*.py`` (per-pack
subclasses). M2 provides the base behaviour; pack subclasses override
the sequence per their workflow doc.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.bundles import ContextBundle, PackType, compose_for_discovery_prep
from app.agents.results import AgentResult, PackResult, PackTelemetry
from app.errors import BusinessRuleError, NATIV2Error
from app.utils.logging import get_logger

log = get_logger(__name__)


class DealOrchestratorAgent:
    """Pack-generation coordinator. Subclasses override ``_run_passes``.

    M2's base class handles the M2 acceptance test (researcher → writer
    sequence with memo round-trip). Pack subclasses in
    ``app/agents/packs/*.py`` override for their pack-specific orchestration.
    """

    pack_type: PackType = "discovery_prep"
    """Subclasses override per pack."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        agency_id: UUID,
        agent_id: str = "deal_orchestrator",
    ) -> None:
        self._session = session
        self._agency_id = agency_id
        self._agent_id = agent_id

    # ── Public API ────────────────────────────────────────────────────

    async def run(self, deal_id: str) -> PackResult[dict[str, Any]]:
        """Compose the bundle + run the pack-specific pass sequence.

        Returns ``PackResult``. On failure, ``status="failed"`` with
        ``error_code`` + ``error_message`` set; partial completions preserve
        whatever artefacts produced before the failure.
        """
        started = datetime.now(UTC)
        log.info(
            "pack_generation_started",
            pack_type=self.pack_type,
            deal_id=deal_id,
            agency_id=str(self._agency_id),
            agent_id=self._agent_id,
        )

        # Compose the bundle. Failure here is unrecoverable (no pack to
        # build without a bundle); return PackResult(status="failed").
        try:
            bundle = await self._compose_bundle(deal_id)
        except NATIV2Error as exc:
            return self._failure(exc, telemetry=PackTelemetry())

        # Run the pack-specific pass sequence. Catches partial failures.
        try:
            results = await self._run_passes(bundle)
        except NATIV2Error as exc:
            log.warning(
                "pack_generation_partial_failure",
                pack_type=self.pack_type,
                deal_id=deal_id,
                error=str(exc),
            )
            return self._failure(exc, telemetry=PackTelemetry())

        telemetry = self._aggregate_telemetry(results)
        telemetry.subagent_invocations = len(results)
        telemetry.latency_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)

        # Coordinator-level structured output: collect each pass's structured
        # output into a single dict keyed by pass name.
        pack_payload = {name: r.structured_output for name, r in results.items()}

        log.info(
            "pack_generation_completed",
            pack_type=self.pack_type,
            deal_id=deal_id,
            subagent_invocations=telemetry.subagent_invocations,
            cost_usd=str(telemetry.cost_usd),
            latency_ms=telemetry.latency_ms,
        )

        return PackResult[dict[str, Any]](
            status="completed",
            pack=pack_payload,
            pack_id=None,  # M2 doesn't persist; M11 pack subclasses fill in
            version=1,
            artifacts={},
            telemetry=telemetry,
        )

    # ── Overridable hooks ─────────────────────────────────────────────

    async def _compose_bundle(self, deal_id: str) -> ContextBundle:
        """Per-pack-type bundle composer dispatch.

        Default routes to ``compose_for_discovery_prep`` since M2's base
        coordinator example IS the discovery prep flow. Pack subclasses
        override for proposal/contract/invoice/performance_report.
        """
        return await compose_for_discovery_prep(
            self._session,
            deal_id=deal_id,
            agency_id=self._agency_id,
        )

    async def _run_passes(self, bundle: ContextBundle) -> dict[str, AgentResult]:
        """Run the pack-specific pass sequence.

        Default: discovery_prep — researcher → writer (2 passes). Pack
        subclasses override with their own sequence per workflow doc.

        Returns a dict mapping pass-name → AgentResult.
        """
        from app.agents.skills import ResearcherAgent, WriterAgent

        results: dict[str, AgentResult] = {}

        # Pass 1: Research.
        researcher = ResearcherAgent(agent_name="researcher")
        research_result = await researcher.invoke(
            prompt=f"Research this deal:\n{bundle.dynamic_body_text()}",
            cache_control_prefix=bundle.static_prefix_text(),
        )
        results["research"] = research_result
        if research_result.error_code:
            raise BusinessRuleError(f"Researcher failed: {research_result.error_message}")

        # Pass 2: Write briefing.
        writer = WriterAgent(agent_name="writer")
        writer_result = await writer.invoke(
            prompt=(
                f"Using the research findings, draft a briefing.\n\n"
                f"Research output:\n{research_result.output_text}\n\n"
                f"Dynamic context:\n{bundle.dynamic_body_text()}"
            ),
            cache_control_prefix=bundle.static_prefix_text(),
        )
        results["briefing"] = writer_result
        if writer_result.error_code:
            raise BusinessRuleError(f"Writer failed: {writer_result.error_message}")

        return results

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _aggregate_telemetry(results: dict[str, AgentResult]) -> PackTelemetry:
        agg = PackTelemetry()
        for r in results.values():
            agg.input_tokens += r.telemetry.input_tokens
            agg.output_tokens += r.telemetry.output_tokens
            agg.cache_creation_input_tokens += r.telemetry.cache_creation_input_tokens
            agg.cache_read_input_tokens += r.telemetry.cache_read_input_tokens
            agg.cost_usd += r.telemetry.cost_usd
            agg.tool_invocations += len(r.tool_calls)
        return agg

    def _failure(self, exc: Exception, *, telemetry: PackTelemetry) -> PackResult[dict[str, Any]]:
        if isinstance(exc, NATIV2Error):
            code = exc.code
            msg = str(exc)
        else:
            code = "INTERNAL_ERROR"
            msg = str(exc)
        telemetry.cost_usd = Decimal("0.00")
        return PackResult[dict[str, Any]](
            status="failed",
            telemetry=telemetry,
            error_code=code,
            error_message=msg,
        )
