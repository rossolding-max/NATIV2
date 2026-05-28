"""Step 4 — Exa web-search fallback for unfilled titles.

For target titles Steps 2 + 3 couldn't fill, run a focused Exa search
(``"<brand_name> <title> linkedin"``), fetch contents for the top
results, and ask Claude to extract any matching person with
``{name, title, linkedin_url, confidence}``. Newly discovered contacts
re-enter the pipeline at Step 3 (LinkedIn enrich) on the next run.

Cost guard: max 3 unfilled titles per run, 1 Exa search and top 5
results each, plus 1 Claude call per title. ``settings.llm_budget_per_pack_usd``
is the hard kill (already enforced by the LLM client).
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.contact_enrichment._models import EnrichedContact
from app.utils.logging import get_logger

log = get_logger(__name__)


DEFAULT_MAX_UNFILLED: int = 3
DEFAULT_RESULTS_PER_QUERY: int = 5
_CONTACT_ID_PREFIX = "bc_"


def _slugify(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return cleaned or "unknown"


def _filled_titles(contacts: list[EnrichedContact]) -> set[str]:
    """Lower-cased set of titles already covered by Step 2 + 3 hits."""
    out: set[str] = set()
    for c in contacts:
        if c.title:
            out.add(c.title.strip().lower())
    return out


def _build_prompt(*, brand_name: str, title: str, contents: list[dict[str, Any]]) -> str:
    snippets = "\n\n".join(
        f"--- Result {i + 1} ---\nURL: {r.get('url', '')}\n{r.get('text', '')[:1500]}"
        for i, r in enumerate(contents)
    )
    return f"""Extract people who currently hold the role "{title}" at "{brand_name}".

Below are web-search results. For each MATCH, return one entry with:
- name: full name as it appears
- title: their exact current title (may differ slightly from the queried role)
- linkedin_url: the LinkedIn profile URL if mentioned
- confidence: 0.0-1.0 based on how clearly the snippet identifies this person at this brand

If no match is found, return an empty list.

Web results:
{snippets}

Respond with JSON ONLY in this exact format (no prose, no markdown fences):
{{
  "matches": [
    {{"name": "...", "title": "...", "linkedin_url": "...", "confidence": 0.85}}
  ]
}}
"""


def _parse_response(text: str) -> list[dict[str, Any]]:
    """Tolerantly parse JSON; fall back to first {...} regex match."""
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s)
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    matches = data.get("matches") if isinstance(data, dict) else None
    if not isinstance(matches, list):
        return []
    out: list[dict[str, Any]] = []
    for item in matches:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        confidence = item.get("confidence")
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(confidence, int | float):
            confidence = 0.5
        out.append(
            {
                "name": name.strip(),
                "title": (item.get("title") or "").strip() or None,
                "linkedin_url": (item.get("linkedin_url") or "").strip() or None,
                "confidence": float(confidence),
            }
        )
    return out


async def run(
    *,
    brand_id: str,
    brand_name: str,
    target_titles: list[str],
    already_filled: list[EnrichedContact],
    max_unfilled: int = DEFAULT_MAX_UNFILLED,
    results_per_query: int = DEFAULT_RESULTS_PER_QUERY,
) -> list[EnrichedContact]:
    """Web-search + LLM-extract contacts for titles Steps 2/3 couldn't fill."""
    if not target_titles:
        return []
    filled = _filled_titles(already_filled)
    unfilled = [t for t in target_titles if t.strip().lower() not in filled][:max_unfilled]
    if not unfilled:
        return []

    # Imports kept local so unit tests don't need to mock Exa / Claude on
    # codepaths where Step 4 isn't reached.
    from app.agents.llm_client import get_async_anthropic
    from app.config import settings
    from app.vendors.exa import ExaClient

    exa = ExaClient()
    client = get_async_anthropic()
    new_contacts: list[EnrichedContact] = []
    seen_keys: set[str] = set()
    # Don't re-surface people already in ``already_filled``.
    for c in already_filled:
        if c.linkedin_url:
            seen_keys.add(c.linkedin_url.lower())
        seen_keys.add(c.name.strip().lower())

    for title in unfilled:
        query = f"{brand_name} {title} LinkedIn"
        try:
            resp = await exa.search(
                query,
                num_results=results_per_query,
                contents={"text": {"includeHtmlTags": False, "maxCharacters": 3000}},
            )
        except Exception as exc:
            log.warning("step_4_exa_search_failed", brand_id=brand_id, title=title, error=str(exc))
            continue
        results = resp.get("results") or []
        if not isinstance(results, list) or not results:
            continue
        prompt = _build_prompt(brand_name=brand_name, title=title, contents=results)
        try:
            response = await client.messages.create(
                model=settings.anthropic_default_model,
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            log.warning("step_4_llm_failed", brand_id=brand_id, title=title, error=str(exc))
            continue
        text_parts: list[str] = []
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", "") or "")
        matches = _parse_response("".join(text_parts))
        for m in matches:
            key = (m.get("linkedin_url") or m["name"]).lower()
            if key in seen_keys:
                continue
            seen_keys.add(key)
            contact = EnrichedContact(
                contact_id=f"{_CONTACT_ID_PREFIX}{brand_id}_{_slugify(m['name'])}"[:96],
                brand_id=brand_id,
                name=m["name"],
                title=m.get("title") or title,
                linkedin_url=m.get("linkedin_url"),
            )
            contact.add_source(
                step="step_4_web_fallback",
                vendor="exa+anthropic",
                payload={
                    "queried_title": title,
                    "query": query,
                    "confidence": m["confidence"],
                },
            )
            new_contacts.append(contact)
    return new_contacts
