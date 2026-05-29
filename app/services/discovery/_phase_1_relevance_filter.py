"""M7.7+ — LLM relevance filter for Phase 1 deterministic proposals.

Runs after the deterministic Phase 1 sources (bidirectional walk,
adjacency, audience, life-stage, exclusivity) and BEFORE the softener,
so the softener generates its suggestions against a clean current-
industry list.

Mechanical taxonomy/adjacency lookups occasionally surface industries
that don't fit the talent's profile — Kevin's dad-life pipeline picks
up ``womenswear`` and ``menstrual-products`` because they're siblings
of his past-brand industries under their parent sectors, but they
aren't commercially relevant to a male dad-life creator.

This filter asks Claude (Haiku) to review the deterministic proposals
against the talent context and flag any that don't fit. Each removal
carries a one-sentence reason so the operator can see WHY it was
pruned (and PATCH-add it back if they disagree).

**Protected sources never removed** — affinity (any tier),
competitor_of_previous, similar_talent. These are deliberate seeds,
not derived noise.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.discovery._models import IndustryProposal
from app.utils.logging import get_logger

log = get_logger(__name__)


_PROTECTED_SOURCES: frozenset[str] = frozenset(
    {
        "affinity_primary",
        "affinity_secondary",
        "affinity_tertiary",
        "competitor_of_previous",
        "similar_talent",
    }
)


def _build_prompt(
    *,
    talent_data: dict[str, Any],
    filterable: list[IndustryProposal],
) -> str:
    niches = list(talent_data.get("content_niches") or [])
    location = (talent_data.get("location") or {}).get("country") or "unspecified"
    audience = talent_data.get("audience_demographics") or {}
    demo_summary = (
        ", ".join(
            f"{k}={v}"
            for k, v in audience.items()
            if isinstance(v, (str, int, float)) and k != "raw"
        )
        or "no oauth-derived audience yet"
    )
    past_brands = talent_data.get("previous_brands") or []
    past_summary = (
        ", ".join(
            f"{(pb.get('brand') or pb.get('name') or '?')} ({pb.get('industry_id') or '?'})"
            for pb in past_brands
            if pb
        )
        or "(none)"
    )

    proposal_block = "\n".join(
        f"  - {p.industry_id} ({p.source}): {p.rationale}" for p in filterable
    )

    return f"""You are reviewing a brand-discovery industry list for relevance.

TALENT CONTEXT:
- Niches: {", ".join(niches) or "(none)"}
- Location: {location}
- Audience signals: {demo_summary}
- Past brands worked with: {past_summary}

DETERMINISTIC INDUSTRY PROPOSALS (taxonomy walks + adjacency tables
generated these mechanically; some may not fit the talent's profile):
{proposal_block}

TASK: identify which of these proposed industries should be REMOVED
because they're clearly irrelevant to this talent's commercial profile.
Examples of bad fits:
- A dad-life MALE creator getting ``womenswear`` or ``menstrual-products``.
- A US-only talent getting ``tourism-boards-uk`` or country-specific
  industries that don't apply.
- A vegan creator getting ``alcohol-spirits`` if values conflict.
- An industry that's commercially adjacent in the taxonomy but
  semantically out-of-scope for this talent's content.

Be CONSERVATIVE: when uncertain, KEEP. Only flag clearly-bad fits.
Do NOT flag industries the talent could plausibly accept a brand deal
in — surface tangents like luxury-goods for a budget-focused creator
ARE often worth keeping unless they're a hard clash.

Return JSON only (no prose, no markdown fences):
{{
  "removals": [
    {{"industry_id": str, "reason": str (one sentence, under 100 chars)}}
  ]
}}
"""


def _parse_response(raw: str) -> list[dict[str, str]]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return []
        try:
            body = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
    raw_removals = body.get("removals") if isinstance(body, dict) else None
    if not isinstance(raw_removals, list):
        return []
    out: list[dict[str, str]] = []
    for entry in raw_removals:
        if not isinstance(entry, dict):
            continue
        iid = entry.get("industry_id")
        reason = entry.get("reason")
        if isinstance(iid, str) and iid.strip():
            out.append(
                {
                    "industry_id": iid.strip(),
                    "reason": str(reason or "").strip()[:200] or "LLM flagged as irrelevant",
                }
            )
    return out


async def filter_irrelevant_proposals(
    proposals: list[IndustryProposal],
    talent_data: dict[str, Any],
    *,
    llm_client: Any = None,
) -> tuple[list[IndustryProposal], list[dict[str, Any]]]:
    """Filter deterministic proposals via one Claude call.

    Returns ``(kept_proposals, removed_records)``.

    - ``kept_proposals`` preserves input order; protected-source items
      stay untouched.
    - ``removed_records`` is a list of dicts ``{industry_id, reason,
      original_source, original_rationale}`` for caller transparency.

    No-op (returns ``(proposals, [])``) when there are no filterable
    proposals or the LLM call fails — fail open, never strip everything.
    """
    if not proposals:
        return proposals, []

    # Split into protected (never filtered) and filterable.
    protected: list[IndustryProposal] = []
    filterable: list[IndustryProposal] = []
    for p in proposals:
        if p.source in _PROTECTED_SOURCES:
            protected.append(p)
        else:
            filterable.append(p)

    if not filterable:
        return proposals, []

    if llm_client is None:
        from app.agents.llm_client import get_async_anthropic

        llm_client = get_async_anthropic()

    prompt = _build_prompt(talent_data=talent_data, filterable=filterable)
    try:
        from app.config import settings

        response = await llm_client.messages.create(
            model=settings.anthropic_default_model,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        log.warning("phase_1_relevance_filter_failed", error=str(exc))
        return proposals, []

    text_parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text_parts.append(getattr(block, "text", "") or "")
    removals = _parse_response("".join(text_parts))
    if not removals:
        return proposals, []

    # Index filterable proposals by industry_id for fast lookup.
    by_id: dict[str, IndustryProposal] = {p.industry_id: p for p in filterable}
    removed_ids: set[str] = set()
    removed_records: list[dict[str, Any]] = []
    for r in removals:
        iid = r["industry_id"]
        if iid not in by_id or iid in removed_ids:
            continue
        original = by_id[iid]
        removed_ids.add(iid)
        removed_records.append(
            {
                "industry_id": iid,
                "reason": r["reason"],
                "original_source": original.source,
                "original_rationale": original.rationale,
            }
        )

    # Reassemble preserving original input order; drop removed.
    kept: list[IndustryProposal] = [p for p in proposals if p.industry_id not in removed_ids]
    log.info(
        "phase_1_relevance_filter_applied",
        input_count=len(proposals),
        protected=len(protected),
        filterable=len(filterable),
        removed=len(removed_ids),
    )
    return kept, removed_records
