"""``WriterAgent`` — drafts pack content using research + bundle.

Tool catalog (allowlist):
- ``read_memos``, ``write_memo`` (memo store).
- ``get_talent``, ``get_deal``, ``get_agency_profile``.
- ``get_top_pitch_angles`` (M2 placeholder algo).
- ``validate_schema`` (validates output against pack schema).
- ``render_template`` (Jinja2).

Memo writes: ``created_by_agent="writer"``. Allowed ``memo_type``:
``negotiation_pattern``, ``creative_insight``, ``objection_handler``.
"""

from __future__ import annotations

from app.agents.base import Agent
from app.agents.skills._prompt_loader import load_prompt


class WriterAgent(Agent):
    """Writing specialist. Loads `app/agents/skills/prompts/writer.md`."""

    model = "claude-opus-4-7"
    system_prompt = load_prompt("writer")
    max_turns = 20
