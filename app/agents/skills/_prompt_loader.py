"""Skill-subagent prompt loader.

Each skill loads its system prompt from a ``.md`` file at module-import time
so the prompt is part of the static prefix Anthropic can cache.
"""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(name: str) -> str:
    """Load a markdown prompt by skill name (e.g. ``"researcher"``)."""
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Skill prompt not found: {path}")
    return path.read_text(encoding="utf-8")
