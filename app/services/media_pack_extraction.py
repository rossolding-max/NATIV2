"""Step 3 — media pack extraction.

Parses uploaded files (PDF / DOCX / image) via the M5 file-parser tool,
then drives a focused Anthropic one-shot prompt asking for the
talent-schema fields the LLM can plausibly fill: ``bio``, ``rate_card``,
``previous_brands``, ``audience_demographics``, ``press_kit``,
``other_stats``.

The output is a list of ``ExtractionCandidate`` entries the wizard
shows the operator in Step 4 reconciliation. Each candidate carries a
confidence score so the UI can sort highest-confidence first.

Persists the raw extraction output to ``data/brand_deals/{talent_id}.json``
for audit per the workflow doc.
"""

from __future__ import annotations

import json
import re
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
    """One auto-fill suggestion the operator reviews in Step 4."""

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
    """Fan files out through ``get_context_artefact``."""
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


# Field-paths the LLM is allowed to suggest. Keeps the prompt focused +
# stops the model from inventing fields outside the talent schema.
_TARGET_FIELDS: list[str] = [
    "bio",
    "date_of_birth",
    "languages",
    "content_niches",
    "audience_demographics",
    "previous_brands",
    "rate_card",
    "press_kit",
    "other_stats",
    "brand_preferences.preferred_industries",
    "working_terms.default_usage_rights",
]


def _build_extraction_prompt(artefacts: list[ContextArtefact]) -> str:
    """Compose the one-shot extraction prompt from the parsed artefacts."""
    blocks: list[str] = []
    for a in artefacts:
        blocks.append(f"--- ARTEFACT {a.artefact_id} ({a.kind}) ---\n{a.text[:30000]}\n")
    artefact_text = "\n".join(blocks) or "(no artefacts provided)"
    field_list = "\n".join(f"  - {f}" for f in _TARGET_FIELDS)
    return f"""You are extracting structured talent profile data from a media kit / press pack.

The agent will REVIEW your output before anything is persisted — your job is to
propose values + confidence scores, not to make final decisions.

Allowed target fields (NOTHING OUTSIDE THIS LIST):
{field_list}

Output a single JSON object with this exact shape:

{{
  "candidates": [
    {{
      "field_path": "bio",
      "value": "...",
      "confidence": 0.0-1.0,
      "evidence": "short quote from the source backing this value"
    }},
    ...
  ]
}}

Rules:
- Only include fields you can support with explicit text from the artefact. Do
  NOT guess. If the source doesn't mention something, omit it.
- ``confidence`` reflects how sure you are the extracted value is correct:
  0.90+ = the source states it verbatim, 0.70-0.89 = strong inference,
  0.50-0.69 = weak/partial signal, below 0.50 = don't include.
- For arrays (``content_niches``, ``previous_brands``, ``languages``,
  ``brand_preferences.preferred_industries``), each candidate is the FULL
  array — don't emit one candidate per element.
- ``rate_card`` shape: {{ "<platform>": {{ "currency": "<ISO 4217>",
  "deliverables": {{ "<deliverable>": {{ "price": <number> }} }} }} }}.
- ``audience_demographics`` shape: {{ "age_bands": [{{...}}],
  "top_countries": [...], "gender_split": {{...}} }} — only fill the
  sub-fields the source actually contains.
- ``previous_brands`` shape: [{{ "brand": "...", "industry_id": "...",
  "year": "..." }}] — ``industry_id`` is optional; omit if unknown.
- ``date_of_birth`` MUST be ISO format (YYYY-MM-DD).
- Languages use BCP-47 codes (e.g. ``en``, ``en-GB``, ``es``).

Return ONLY the JSON object. No prose, no markdown fences.

SOURCE ARTEFACTS:

{artefact_text}
"""


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json_block(text: str) -> str:
    """Strip ```json``` fences if present (defensive — the prompt forbids them)."""
    m = _JSON_FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


def _parse_candidates(
    raw_text: str, *, source_artefact_id: str
) -> tuple[list[ExtractionCandidate], list[str]]:
    """Parse the LLM JSON output into ExtractionCandidate entries."""
    errors: list[str] = []
    candidates: list[ExtractionCandidate] = []
    try:
        body = json.loads(_extract_json_block(raw_text))
    except json.JSONDecodeError as exc:
        errors.append(f"llm_response_not_json: {exc}")
        return candidates, errors
    raw_candidates = body.get("candidates") or []
    if not isinstance(raw_candidates, list):
        errors.append("llm_response_candidates_not_a_list")
        return candidates, errors
    for entry in raw_candidates:
        if not isinstance(entry, dict):
            continue
        field_path = entry.get("field_path")
        value = entry.get("value")
        confidence = entry.get("confidence")
        if not field_path or field_path not in _TARGET_FIELDS:
            continue  # silently drop out-of-scope fields
        if not isinstance(confidence, int | float):
            continue
        candidates.append(
            ExtractionCandidate(
                field_path=str(field_path),
                value=value,
                confidence=float(confidence),
                source_artefact_id=source_artefact_id,
            )
        )
    return candidates, errors


async def _run_llm_extraction(
    artefacts: list[ContextArtefact],
) -> tuple[list[ExtractionCandidate], list[str]]:
    """Call Anthropic one-shot, return parsed candidates + errors."""
    from app.agents.llm_client import get_async_anthropic
    from app.config import settings

    client = get_async_anthropic()
    prompt = _build_extraction_prompt(artefacts)
    log.info("media_pack_llm_extraction_started", artefact_count=len(artefacts))
    try:
        response = await client.messages.create(
            model=settings.anthropic_default_model,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        log.warning("media_pack_llm_extraction_failed", error=str(exc))
        return [], [f"llm_extraction_failed: {exc}"]

    # The SDK returns ``content`` as a list of content blocks; the first
    # text block carries the JSON.
    text_parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text_parts.append(getattr(block, "text", "") or "")
    raw_text = "".join(text_parts)
    if not raw_text:
        return [], ["llm_response_empty"]

    source_id = artefacts[0].artefact_id if artefacts else "unknown"
    return _parse_candidates(raw_text, source_artefact_id=source_id)


async def extract_from_files(
    talent_id: str,
    *,
    s3_keys: list[str] | None = None,
    raw_inputs: list[dict[str, Any]] | None = None,
    run_llm_extraction: bool = True,
    audit_dir: Path | None = None,
) -> ExtractionResult:
    """Full Step-3 pipeline: parse files → run LLM → audit-dump.

    Default ``run_llm_extraction=True`` because the wizard's intent is
    to surface candidates back to the operator for Step 4 reconciliation;
    tests can pass ``False`` to skip the live LLM call and just exercise
    the file-parser path.
    """
    artefacts = await parse_uploaded_files(talent_id, s3_keys=s3_keys, raw_inputs=raw_inputs)
    candidates: list[ExtractionCandidate] = []
    errors: list[str] = []

    if run_llm_extraction and artefacts:
        cand_list, err_list = await _run_llm_extraction(artefacts)
        candidates.extend(cand_list)
        errors.extend(err_list)
        log.info(
            "media_pack_llm_extraction_done",
            talent_id=talent_id,
            candidate_count=len(candidates),
            error_count=len(errors),
        )

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
