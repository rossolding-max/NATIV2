"""Step 7 — similar-talent seeds + LLM-suggested candidates.

7A: agency adds manual seeds (talents they think are comparable). v0.1
ships this path fully.

7B: LLM suggests 3-5 candidates given content_niches +
audience_demographics. v0.1 ships the prompt-building helper but defers
the actual Anthropic call to M7 (Brand Discovery), where the cassette
infrastructure for live-LLM tests already exists.

HypeAuditor / CreatorIQ / Modash integration is v2.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SimilarTalentSeed:
    """Structure persisted into ``talent.data.similar_talent[N]``."""

    id: str
    name: str
    handles: list[str]
    research_status: str = "seed"


def build_seed_entry(
    *,
    name: str,
    handles: Sequence[str | dict[str, Any]],
    slug: str | None = None,
) -> dict[str, Any]:
    """Translate a manual seed into the JSONB shape the workflow expects.

    Accepts handles as either strings (``"@janedoe"``) or pre-shaped objects
    (``{"platform": "instagram", "handle": "@janedoe"}``). String entries
    are normalized to ``{"platform": "unknown", "handle": ...}`` so the
    result matches the talent.schema.json ``handles[]`` item shape.
    """
    seed_id = (slug or name).strip().lower().replace(" ", "-")
    normalized: list[dict[str, Any]] = []
    for h in handles:
        if isinstance(h, dict):
            normalized.append(h)
        else:
            normalized.append({"platform": "unknown", "handle": str(h)})
    return {
        "id": seed_id,
        "name": name,
        "handles": normalized,
        "research": {"status": "seed"},
    }


def add_seed_to_data(data: dict[str, Any], seed: dict[str, Any]) -> list[dict[str, Any]]:
    """Append a seed (de-duped by id) and return the updated array."""
    existing: list[dict[str, Any]] = list(data.get("similar_talent") or [])
    seed_id = seed.get("id")
    if not any(s.get("id") == seed_id for s in existing):
        existing.append(seed)
    return existing


def build_suggestion_prompt(data: dict[str, Any], count: int = 5) -> str:
    """Compose a Claude prompt for LLM-suggested similar talent.

    v0.1 ships the prompt; the LLM call itself is wired in M7 alongside
    the brand-discovery suggestion loop (shared infrastructure).
    """
    niches = ", ".join(data.get("content_niches") or []) or "<no niches set>"
    demo = data.get("audience_demographics") or {}
    age_bands = demo.get("age_bands") or []
    geo = demo.get("top_countries") or []
    return (
        f"Suggest {count} influencer creators similar to the talent below "
        f"(same niches + similar audience). Return JSON list of "
        f"{{name, handles[], why}} entries.\n\n"
        f"Talent niches: {niches}\n"
        f"Audience age bands: {age_bands}\n"
        f"Top countries: {geo}\n"
    )
