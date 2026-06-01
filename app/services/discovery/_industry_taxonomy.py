"""M7.7 — Derive top-level industry + sub-industry from a single industry_id.

`industries.json` is a 2-level taxonomy: top-level sectors (parent=None) +
sub-industries (parent set to the sector id). A brand classified under
``sportswear`` is actually:
  - Top-level industry: ``sports-outdoor`` (the sector)
  - Sub-industry: ``sportswear``

A brand classified under ``grocery`` is:
  - Top-level industry: ``grocery`` (itself — no parent)
  - Sub-industry: None

This module surfaces both as first-class fields on every M7.7 candidate
so the agent UI can show industry/sub-industry without walking the
taxonomy.
"""

from __future__ import annotations

from app.utils.taxonomies import Taxonomies


def derive_top_level_and_sub_industry(
    industry_id: str,
    taxonomies: Taxonomies,
) -> tuple[str, str | None]:
    """Return ``(top_level_industry_id, sub_industry_id | None)``.

    - If ``industry_id`` is a top-level sector (no parent), returns
      ``(industry_id, None)``.
    - If ``industry_id`` is a sub-industry, returns
      ``(parent_industry_id, industry_id)``.
    - If ``industry_id`` isn't in the taxonomy at all (LLM hallucination
      or stale data), returns ``(industry_id, None)`` so the candidate
      still gets a usable industry_id; caller can log a warning.
    """
    parent = taxonomies.get_industry_parent(industry_id)
    # Defensive: callers (orchestrator tests) sometimes pass MagicMock
    # taxonomies whose get_industry_parent returns a Mock object instead
    # of None. Only treat the return as a parent when it's a real string.
    if not isinstance(parent, str) or not parent:
        return industry_id, None
    return parent, industry_id
