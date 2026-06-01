"""Step 6 — Claude classifier: decision_role + outreach_recommendation (M8.1).

Takes the candidate list (with title + seniority + function from
Steps 2/3) and the brand metadata (revenue, headcount, tier, stage)
and returns TWO classifications per contact in ONE batched LLM call:

1. ``decision_role`` (five values): the contact's role in the buying
   decision — buyer / influencer / gatekeeper / champion / unknown.

2. ``outreach_recommendation`` (three values, M8.1): whether the
   operator should actually pitch this contact directly.
   - ``recommended``: clear-fit role + appropriate seniority for a
     direct pitch. (e.g. Influencer Marketing Manager at any brand;
     Brand Manager at mid-size brand; Founder at <500-person brand.)
   - ``not_recommended``: structurally wrong target — too senior to
     respond to direct creator pitches (CMO at $50B brand), wrong
     function (procurement reviewer), or known dead-end (placeholder
     row with no name).
   - ``requires_review``: ambiguous signal; operator should look at the
     row before deciding.

Both classifications come from one prompt → one JSON response → one
parse. Parse failures default to ``unknown`` + ``requires_review`` so
nothing surfaces as ``recommended`` without an actual LLM endorsement.

Mirrors the ``search_13_values_aligned.py`` prompt + tolerant
JSON-parser pattern. One LLM call per enrichment run — cheap.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.contact_enrichment._models import EnrichedContact
from app.utils.logging import get_logger

log = get_logger(__name__)


_ALLOWED_ROLES: frozenset[str] = frozenset(
    {"buyer", "influencer", "gatekeeper", "champion", "unknown"}
)

_ALLOWED_RECOMMENDATIONS: frozenset[str] = frozenset(
    {"recommended", "not_recommended", "requires_review"}
)


def _build_prompt(*, brand_metadata: dict[str, Any], contacts: list[EnrichedContact]) -> str:
    brand_summary = json.dumps(
        {
            "name": brand_metadata.get("name"),
            "typical_campaign_tier": brand_metadata.get("typical_campaign_tier"),
            "company_stage": brand_metadata.get("company_stage"),
            "revenue_band": (brand_metadata.get("revenue") or {}).get("amount_usd"),
            "headcount_band": (brand_metadata.get("headcount") or {}).get("band"),
        },
        indent=2,
    )
    candidates_block = "\n".join(
        f"  - {c.contact_id}: {c.name} | title={c.title or 'unknown'} | "
        f"seniority={c.seniority or 'unknown'}"
        for c in contacts
    )
    return f"""You are classifying business-development contacts at a brand for a
talent agency planning to pitch an influencer-marketing deal. For each
contact, return TWO independent classifications.

Brand metadata:
{brand_summary}

Contacts:
{candidates_block}

CLASSIFICATION 1 — decision_role (role in the buying decision):
- "buyer": can say yes AND holds budget (founders at small/mid brands,
  CMOs at small brands, VPs at $1B+ brands, Influencer Marketing
  Manager / Director of Creator Partnerships at any brand size).
- "influencer": has input but not final authority (mid-level marketers
  at large brands; CMOs/VPs at megabrands where deal sign-off happens
  2-3 levels below).
- "gatekeeper": controls access to the buyer (EAs, AOR account
  directors, procurement).
- "champion": internal advocate for influencer marketing or this
  talent type (rare — only when there's explicit signal).
- "unknown": insufficient signal to classify.

CLASSIFICATION 2 — outreach_recommendation (M8.1):
Should the operator pitch this contact DIRECTLY?
- "recommended": yes — clear-fit role at the right level for a creator
  pitch (Influencer Marketing Manager anywhere, Founder at <500-person
  brand, Senior Brand Manager at mid-market). Email reveal worth paying
  for.
- "not_recommended": no — structurally wrong target. Examples: CMO at
  $50B brand (too senior; will ignore or forward), procurement
  reviewer, anyone whose title suggests they don't own creator-
  marketing decisions, placeholder rows with "Unknown" name.
- "requires_review": ambiguous — operator should look at the row
  before deciding (e.g. unclear title, unfamiliar role).

When in doubt, prefer "requires_review" over "recommended". The
purpose of this flag is to save the operator email-reveal spend on
contacts who'd never respond to a direct creator pitch.

Respond with JSON ONLY in this exact format (no prose, no markdown
fences):
{{
  "classifications": [
    {{
      "contact_id": "...",
      "decision_role": "buyer|influencer|gatekeeper|champion|unknown",
      "decision_role_rationale": "one sentence",
      "outreach_recommendation": "recommended|not_recommended|requires_review",
      "outreach_recommendation_rationale": "one sentence"
    }}
  ]
}}
"""


def _parse_response(text: str) -> dict[str, dict[str, str]]:
    """Return a contact_id -> {role, role_rationale, recommendation,
    recommendation_rationale} map.

    Backwards compatible: pre-M8.1 Haiku responses with only ``rationale``
    (single key, decision_role rationale) still parse correctly; the
    recommendation fields fall back to ``requires_review`` + empty
    rationale when missing.
    """
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s)
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if not m:
            return {}
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return {}
    classifications = data.get("classifications") if isinstance(data, dict) else None
    if not isinstance(classifications, list):
        return {}
    out: dict[str, dict[str, str]] = {}
    for item in classifications:
        if not isinstance(item, dict):
            continue
        cid = item.get("contact_id")
        role = item.get("decision_role")
        if not isinstance(cid, str) or not isinstance(role, str):
            continue
        role = role.strip().lower()
        if role not in _ALLOWED_ROLES:
            role = "unknown"
        # decision_role_rationale: new field name post-M8.1; legacy
        # ``rationale`` key supported for backwards compat.
        role_rationale = item.get("decision_role_rationale")
        if not isinstance(role_rationale, str) or not role_rationale.strip():
            role_rationale = item.get("rationale") or ""
        # outreach_recommendation: new in M8.1. Default to requires_review
        # when missing or invalid — never auto-promote to recommended.
        recommendation = item.get("outreach_recommendation")
        if isinstance(recommendation, str):
            recommendation = recommendation.strip().lower()
        if recommendation not in _ALLOWED_RECOMMENDATIONS:
            recommendation = "requires_review"
        recommendation_rationale = item.get("outreach_recommendation_rationale") or ""
        out[cid] = {
            "role": role,
            "role_rationale": str(role_rationale).strip(),
            "recommendation": recommendation,
            "recommendation_rationale": str(recommendation_rationale).strip(),
        }
    return out


async def run(
    *,
    contacts: list[EnrichedContact],
    brand_metadata: dict[str, Any],
) -> list[EnrichedContact]:
    """Classify each contact's ``decision_role`` in ONE batched LLM call.

    Fail-soft: if the LLM call errors or returns malformed output, leaves
    ``decision_role="unknown"`` on every contact (the dataclass default).
    """
    if not contacts:
        return contacts

    from app.agents.llm_client import get_async_anthropic
    from app.config import settings

    client = get_async_anthropic()
    prompt = _build_prompt(brand_metadata=brand_metadata, contacts=contacts)
    try:
        response = await client.messages.create(
            model=settings.anthropic_default_model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        log.warning("step_6_llm_failed", error=str(exc))
        return contacts

    text_parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text_parts.append(getattr(block, "text", "") or "")
    classifications = _parse_response("".join(text_parts))
    for c in contacts:
        entry = classifications.get(c.contact_id)
        if entry is None:
            continue
        c.decision_role = entry["role"]
        c.decision_role_rationale = entry["role_rationale"]
        c.outreach_recommendation = entry["recommendation"]
        c.outreach_recommendation_rationale = entry["recommendation_rationale"]
    return contacts
