"""``ExtractorAgent`` — parses uploaded files (PDF + DOCX) into structured data.

Tool catalog (allowlist):
- ``read_memos``, ``write_memo`` (memo store).
- ``get_context_artefact`` (M2 stub; real impl in M5/M12 with pypdf +
  python-docx parsing).

Memo writes: ``created_by_agent="extractor"``. Allowed ``memo_type``:
``kpi_pattern``, ``talent_learning``.

M2 ships this skill as a class scaffold. First real use case is M5
(talent media pack extraction) or M12 (proposal context uploads). The
discovery_prep example in M2 PR 2 does NOT invoke the extractor.
"""

from __future__ import annotations

from app.agents.base import Agent
from app.agents.skills._prompt_loader import load_prompt


class ExtractorAgent(Agent):
    """File-parsing specialist. Loads `app/agents/skills/prompts/extractor.md`."""

    model = "claude-opus-4-7"
    system_prompt = load_prompt("extractor")
    max_turns = 10
