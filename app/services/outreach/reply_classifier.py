"""Claude reply classifier — one call per reply, JSON-only output.

Mirrors the M7 Search 13 / M8 Step 6 batched-LLM pattern. Returns
``OutcomeClassification``:

- ``outcome`` ∈ {interested, declined, out_of_office, unrelated,
  unsubscribe_request, needs_more_info, wrong_person_routed}
- ``confidence`` ∈ [0, 1]
- ``rationale`` — one sentence
- ``extracted_signals`` — structured fields callers read:
  ``asked_for_meeting``, ``asked_for_pricing``, ``asked_for_more_info``,
  ``objections_raised``, ``next_step_proposed``, ``ooo_until``,
  ``routed_to_contact``

Fail-soft to ``outcome="needs_more_info"`` + ``confidence=0.0`` on any
LLM error or malformed response.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.utils.logging import get_logger

log = get_logger(__name__)


_ALLOWED_OUTCOMES: frozenset[str] = frozenset(
    {
        "interested",
        "declined",
        "out_of_office",
        "unrelated",
        "unsubscribe_request",
        "needs_more_info",
        "wrong_person_routed",
    }
)


@dataclass
class OutcomeClassification:
    """Structured output of one reply classification."""

    outcome: str = "needs_more_info"
    confidence: float = 0.0
    rationale: str = ""
    extracted_signals: dict[str, Any] = field(default_factory=dict)


def _build_prompt(
    *,
    reply_body: str,
    enrollment_subject: str | None,
    contact_name: str | None,
    talent_name: str | None,
    brand_name: str | None,
) -> str:
    return f"""You are classifying a reply to a cold outreach email.

Context:
- Talent agency representing: {talent_name or "Unknown"}
- Pitched to: {contact_name or "Unknown"} at {brand_name or "Unknown"}
- Original email subject: {enrollment_subject or "Unknown"}

Reply body:
{reply_body.strip()[:4000]}

Classify into ONE of:
- interested: positive signal; wants to discuss / asked for next step / meeting
- declined: clear no; not a fit, wrong time, etc.
- out_of_office: auto-OOO; extract ooo_until date if mentioned
- unrelated: not about our outreach (spam reply, unrelated thread)
- unsubscribe_request: asked to be removed from outreach
- needs_more_info: ambiguous or asked clarifying questions
- wrong_person_routed: forwarded to / says ask someone else

Also extract structured signals.

Respond with JSON ONLY in this exact format (no prose, no markdown
fences):
{{
  "outcome": "...",
  "confidence": 0.0,
  "rationale": "one sentence",
  "extracted_signals": {{
    "asked_for_meeting": false,
    "asked_for_pricing": false,
    "asked_for_more_info": false,
    "objections_raised": [],
    "next_step_proposed": null,
    "ooo_until": null,
    "routed_to_contact": null
  }}
}}
"""


def _parse_response(text: str) -> dict[str, Any] | None:
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s)
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


async def classify_reply(
    *,
    reply_body: str,
    enrollment_subject: str | None = None,
    contact_name: str | None = None,
    talent_name: str | None = None,
    brand_name: str | None = None,
    model: str | None = None,
) -> OutcomeClassification:
    """Single Haiku call classifying one reply."""
    from app.agents.llm_client import get_async_anthropic

    client = get_async_anthropic()
    chosen_model = model or "claude-haiku-4-5"
    prompt = _build_prompt(
        reply_body=reply_body,
        enrollment_subject=enrollment_subject,
        contact_name=contact_name,
        talent_name=talent_name,
        brand_name=brand_name,
    )
    try:
        response = await client.messages.create(
            model=chosen_model,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        log.warning("reply_classifier_llm_error", error=str(exc))
        return OutcomeClassification(rationale=f"llm_error:{exc}")

    text_parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text_parts.append(getattr(block, "text", "") or "")
    parsed = _parse_response("".join(text_parts))
    if parsed is None:
        log.warning("reply_classifier_unparseable")
        return OutcomeClassification(rationale="unparseable_json")

    outcome = str(parsed.get("outcome") or "").strip().lower()
    if outcome not in _ALLOWED_OUTCOMES:
        outcome = "needs_more_info"
    confidence = parsed.get("confidence", 0.0)
    if not isinstance(confidence, int | float):
        confidence = 0.0
    signals = parsed.get("extracted_signals") or {}
    if not isinstance(signals, dict):
        signals = {}
    return OutcomeClassification(
        outcome=outcome,
        confidence=float(max(0.0, min(1.0, confidence))),
        rationale=str(parsed.get("rationale") or ""),
        extracted_signals=signals,
    )
