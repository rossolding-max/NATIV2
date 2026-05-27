"""``ResearcherAgent`` — gathers facts (memos + brand data + past deals).

Tool catalog (allowlist):
- ``read_memos``, ``write_memo`` (bound at construction per
  ``app.agents.tools.memo_tools.bind_memo_tools``).
- ``get_brand_record``, ``get_brand_deals_for_talent``,
  ``get_brand_deals_for_brand_across_talents`` (M2 PR 2 stubs;
  real impls land in their owning milestones).
- ``exa_search`` + ``web_fetch`` — M3 vendor wrapper stubs; raise at runtime.

Memo writes: ``created_by_agent="researcher"`` (constructor-bound; not
Claude-controlled). Allowed ``memo_type``: ``brand_observation``,
``industry_insight``.
"""

from __future__ import annotations

from app.agents.base import Agent
from app.agents.skills._prompt_loader import load_prompt


class ResearcherAgent(Agent):
    """Research specialist. Loads `app/agents/skills/prompts/researcher.md`."""

    model = "claude-opus-4-7"
    system_prompt = load_prompt("researcher")
    max_turns = 15
