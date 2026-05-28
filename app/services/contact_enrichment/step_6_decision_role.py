"""Step 6 — Claude ``decision_role`` classifier (one batched call per run).

Takes the candidate list (with title + seniority + function from
Steps 2/3) and the brand metadata (revenue, headcount, tier, stage)
and returns one of five ``decision_role`` values per contact:

- ``buyer`` — can say yes AND holds budget for this deal size
- ``influencer`` — has input but not authority
- ``gatekeeper`` — controls access to the buyer
- ``champion`` — internal advocate / known fan of this talent type
- ``unknown`` — insufficient signal (default fallback)

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
talent agency planning to pitch an influencer-marketing deal.

Brand metadata:
{brand_summary}

For each contact below, decide their ROLE in the buying decision:
- "buyer": can say yes AND holds budget (founders at small/mid brands,
  CMOs at small brands, VPs at $1B+ brands).
- "influencer": has input but not final authority (mid-level marketers
  at large brands).
- "gatekeeper": controls access to the buyer (EAs, AOR contacts).
- "champion": internal advocate for influencer marketing or this
  talent type.
- "unknown": insufficient signal to classify.

Contacts:
{candidates_block}

Respond with JSON ONLY in this exact format (no prose, no markdown
fences):
{{
  "classifications": [
    {{
      "contact_id": "...",
      "decision_role": "buyer|influencer|gatekeeper|champion|unknown",
      "rationale": "one sentence"
    }}
  ]
}}
"""


def _parse_response(text: str) -> dict[str, dict[str, str]]:
    """Return a contact_id -> {role, rationale} map."""
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
        rationale = item.get("rationale") or ""
        out[cid] = {"role": role, "rationale": str(rationale).strip()}
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
        c.decision_role_rationale = entry["rationale"]
    return contacts
