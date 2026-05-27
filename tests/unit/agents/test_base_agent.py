"""Unit tests for ``app.agents.base.Agent`` — no DB, no LLM, no cassettes.

These exercise the structural surface:
- ``ToolSpec`` instantiation.
- Class-level ``model``, ``system_prompt``, ``tools`` overrides.
- ``Agent.__init__`` lazy-binds the Anthropic singleton.
- ``Agent._anthropic_tool_specs`` builds the right Anthropic tool-spec shape.

Cassette-based end-to-end tests live in
``tests/integration/agents/test_skill_subagents_cassette.py`` (M2 PR 2).
"""

from __future__ import annotations

from typing import Any

from app.agents.base import Agent, ToolSpec


class _ProbeAgent(Agent):
    """Test subclass with a registered tool."""

    model = "claude-opus-4-7"
    system_prompt = "You are a test probe."
    max_turns = 5


def test_unit__toolspec_carries_callable_and_schema() -> None:
    async def _noop(**_kwargs: Any) -> str:
        return "ok"

    spec = ToolSpec(
        "echo",
        _noop,
        {"description": "echo tool", "input_schema": {"type": "object"}},
    )
    assert spec.name == "echo"
    assert spec.callable_ is _noop
    assert spec.json_schema["description"] == "echo tool"


def test_unit__agent_init_uses_singleton_anthropic_client() -> None:
    """Two Agent instances share the same client object (singleton pattern)."""
    a = _ProbeAgent()
    b = _ProbeAgent()
    assert a._client is b._client  # type: ignore[attr-defined]


def test_unit__agent_anthropic_tool_specs_returns_none_when_empty() -> None:
    agent = _ProbeAgent()
    assert agent._anthropic_tool_specs() is None  # type: ignore[attr-defined]


def test_unit__agent_anthropic_tool_specs_serialises_catalog() -> None:
    async def _echo(text: str) -> str:
        return text

    spec = ToolSpec(
        "echo",
        _echo,
        {
            "description": "Echo the input text.",
            "input_schema": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    )

    class _ToolAgent(Agent):
        tools = {"echo": spec}

    agent = _ToolAgent()
    result = agent._anthropic_tool_specs()  # type: ignore[attr-defined]
    assert result is not None
    assert len(result) == 1
    assert result[0]["name"] == "echo"
    assert result[0]["description"] == "Echo the input text."
    assert "input_schema" in result[0]


def test_unit__agent_name_defaults_to_class_name() -> None:
    agent = _ProbeAgent()
    assert agent.agent_name == "_ProbeAgent"
    custom = _ProbeAgent(agent_name="researcher")
    assert custom.agent_name == "researcher"


def test_unit__try_parse_json_handles_text() -> None:
    """``_try_parse_json`` returns dict for object payloads, None for prose."""
    agent = _ProbeAgent()
    assert agent._try_parse_json('{"key": "value"}') == {"key": "value"}  # type: ignore[attr-defined]
    assert agent._try_parse_json("just prose") is None  # type: ignore[attr-defined]
    assert agent._try_parse_json(None) is None  # type: ignore[attr-defined]
    assert agent._try_parse_json('["array", "not", "dict"]') is None  # type: ignore[attr-defined]
