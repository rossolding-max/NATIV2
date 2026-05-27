"""Skill subagents for M2+ pack generation.

4 skill specialists, each a concrete ``Agent`` subclass. System prompts
live in ``app/agents/skills/prompts/*.md`` (git-reviewable + cacheable).
"""

from __future__ import annotations

from app.agents.skills.extractor import ExtractorAgent
from app.agents.skills.renderer import RendererAgent
from app.agents.skills.researcher import ResearcherAgent
from app.agents.skills.writer import WriterAgent

__all__ = ["ExtractorAgent", "RendererAgent", "ResearcherAgent", "WriterAgent"]
