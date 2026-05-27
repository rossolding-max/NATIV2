"""``RendererAgent`` — non-LLM Jinja2 + python-docx + Playwright wrapper.

Unlike the other skill subagents, this one does NOT call Claude. It exists
as an Agent subclass for symmetry (coordinator can invoke it via the same
interface as the others). Its ``invoke`` override is deterministic and
synchronous.

v0.1 ships markdown deliverables only (per V2-PACK-01); HTML decks +
PDF rendering land in v2.
"""

from __future__ import annotations

from typing import Any

import jinja2

from app.agents.base import Agent
from app.agents.results import AgentResult, AgentTelemetry
from app.agents.skills._prompt_loader import load_prompt

# Jinja2 environment with autoescape on by default (ruff S701).
_jinja_env: jinja2.Environment | None = None


def _get_jinja_env() -> jinja2.Environment:
    global _jinja_env
    if _jinja_env is None:
        _jinja_env = jinja2.Environment(autoescape=True, keep_trailing_newline=True)
    return _jinja_env


class RendererAgent(Agent):
    """Non-LLM rendering wrapper. Overrides ``invoke`` to skip Anthropic."""

    model = "renderer-noop"  # No LLM; cost telemetry is always zero.
    system_prompt = load_prompt("renderer")
    max_turns = 1

    async def invoke(  # type: ignore[override]
        self,
        prompt: str,
        *,
        cache_control_prefix: str | None = None,
        extra_system: str | None = None,
        template_string: str | None = None,
        template_context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Render a Jinja2 template + return as the result.

        The renderer doesn't follow the Anthropic-call interface — it
        accepts ``template_string`` + ``template_context`` directly. The
        ``prompt`` arg is ignored (kept for signature compatibility with
        the base Agent class).
        """
        _ = prompt
        _ = cache_control_prefix
        _ = extra_system
        if template_string is None:
            return AgentResult(
                output_text=None,
                telemetry=AgentTelemetry(model=self.model),
                error_code="VALIDATION_ERROR",
                error_message="template_string is required for RendererAgent.invoke",
            )

        env = _get_jinja_env()
        template = env.from_string(template_string)
        rendered = template.render(**(template_context or {}))
        return AgentResult(
            output_text=rendered,
            telemetry=AgentTelemetry(model=self.model),
        )
