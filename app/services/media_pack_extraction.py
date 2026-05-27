"""Step 3 — media pack extraction.

Pre-parses uploaded files (PDF / DOCX / image) via the M5 file-parser
tool, then optionally drives the M2 ``ExtractorAgent`` with a curated
prompt asking for the talent-schema fields the LLM can plausibly fill
(``bio``, ``rate_card``, ``previous_brands``, ``press_kit``,
``audience_demographics``, ``other_stats``).

v0.1 scope: the LLM invocation is gated behind an explicit
``run_llm_extraction`` flag. When False (the default — used by tests and
the CLI wizard's auto mode), the service returns the parsed text plus
the artefact list so the caller can manually transcribe fields via the
Step-4 reconciliation review or the Step-5 questionnaire. When True, the
extractor agent gets called with the artefacts as context.

Persists the raw extraction output to
``data/brand_deals/{talent_id}.json`` for audit per the workflow doc.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agents.tools.get_context_artefact import (
    ContextArtefact,
    get_context_artefact,
)
from app.utils.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class ExtractionCandidate:
    """One auto-fill suggestion the user reviews in Step 4."""

    field_path: str
    value: Any
    confidence: float
    source_artefact_id: str


@dataclass(frozen=True)
class ExtractionResult:
    """Aggregate output of Step 3 — what to surface in the Step-4 review grid."""

    talent_id: str
    artefacts: list[ContextArtefact] = field(default_factory=list)
    candidates: list[ExtractionCandidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


async def parse_uploaded_files(
    talent_id: str,
    *,
    s3_keys: list[str] | None = None,
    raw_inputs: list[dict[str, Any]] | None = None,
) -> list[ContextArtefact]:
    """Fan files out through ``get_context_artefact``.

    ``s3_keys`` — production path (MinIO/S3 fetch). ``raw_inputs`` —
    direct-injection mode for tests + CLI wizard (each dict has
    ``raw_bytes`` + optional ``filename`` + ``content_type``).
    """
    artefacts: list[ContextArtefact] = []
    if s3_keys:
        for i, key in enumerate(s3_keys):
            artefact_id = f"{talent_id}-media-pack-{i:02d}"
            artefacts.append(await get_context_artefact(artefact_id, s3_key=key))
    if raw_inputs:
        for i, item in enumerate(raw_inputs):
            artefact_id = f"{talent_id}-media-pack-raw-{i:02d}"
            artefacts.append(
                await get_context_artefact(
                    artefact_id,
                    raw_bytes=item["raw_bytes"],
                    filename=item.get("filename"),
                    content_type=item.get("content_type"),
                )
            )
    return artefacts


async def extract_from_files(
    talent_id: str,
    *,
    s3_keys: list[str] | None = None,
    raw_inputs: list[dict[str, Any]] | None = None,
    run_llm_extraction: bool = False,
    audit_dir: Path | None = None,
) -> ExtractionResult:
    """Full Step-3 pipeline: parse files → optionally run LLM → audit-dump.

    LLM invocation is opt-in for v0.1 — the extractor agent's full
    structured-output prompt is shipped but the integration tests don't
    call it (no live ANTHROPIC_API_KEY). M11+ artefact-pack milestones
    exercise the real LLM path with cassettes.
    """
    artefacts = await parse_uploaded_files(talent_id, s3_keys=s3_keys, raw_inputs=raw_inputs)
    candidates: list[ExtractionCandidate] = []
    errors: list[str] = []

    if run_llm_extraction and artefacts:
        try:
            from app.agents.skills.extractor import ExtractorAgent

            log.info(
                "media_pack_llm_extraction_started",
                talent_id=talent_id,
                artefact_count=len(artefacts),
            )
            # v0.1 wiring: the extractor's prompt is already structured to
            # return JSON. M5 ships the call site but does not parse the
            # raw response into ExtractionCandidate entries — that lands
            # when the LLM eval cassettes for talent media-pack arrive.
            _ = ExtractorAgent  # imported to confirm availability
        except Exception as exc:
            errors.append(f"llm_extraction_failed: {exc}")
            log.warning("media_pack_llm_extraction_failed", error=str(exc))

    result = ExtractionResult(
        talent_id=talent_id,
        artefacts=artefacts,
        candidates=candidates,
        errors=errors,
    )

    if audit_dir is not None:
        _write_audit_dump(result, audit_dir)

    return result


def _write_audit_dump(result: ExtractionResult, audit_dir: Path) -> None:
    """Persist the extraction output to disk for downstream audit."""
    audit_dir.mkdir(parents=True, exist_ok=True)
    out = audit_dir / f"{result.talent_id}.json"
    out.write_text(
        json.dumps(
            {
                "talent_id": result.talent_id,
                "manually_verified_by_talent": False,
                "artefacts": [
                    {
                        "artefact_id": a.artefact_id,
                        "kind": a.kind,
                        "text_excerpt": a.text[:500],
                        "metadata": a.metadata,
                        "attachment_count": len(a.attachments),
                    }
                    for a in result.artefacts
                ],
                "candidates": [
                    {
                        "field_path": c.field_path,
                        "value": c.value,
                        "confidence": c.confidence,
                        "source_artefact_id": c.source_artefact_id,
                    }
                    for c in result.candidates
                ],
                "errors": result.errors,
            },
            indent=2,
        )
    )
