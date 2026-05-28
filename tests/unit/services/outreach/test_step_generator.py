"""Per-step LLM generator — validates JSON parsing + guardrail enforcement."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.outreach import step_generator


def _llm_response(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


def _angle(angle_id: str, category: str = "role_default") -> MagicMock:
    a = MagicMock()
    a.angle_id = angle_id
    a.category = category
    a.name = angle_id
    a.data = {"example_phrasing": f"example for {angle_id}"}
    return a


def _template(*, max_body: int = 600, max_subject: int = 60) -> dict[str, Any]:
    return {
        "guardrails": {
            "max_body_chars": max_body,
            "max_subject_chars": max_subject,
            "tone": "direct_professional",
        }
    }


def _step() -> dict[str, Any]:
    return {
        "step_number": 1,
        "intent": "first_touch_strongest_angle",
        "timing_offset_days": 0,
        "ai_model_override": "claude-haiku-4-5",
    }


@pytest.mark.asyncio
async def test_unit__step_generator__happy_path() -> None:
    response = _llm_response(
        '{"subject": "Quick intro", "body": "Hi there, want to chat?", '
        '"angles_used": {"primary": "ang_1", "supporting": null}, '
        '"personalization_fields_used": ["contact.name"], '
        '"reasoning": "fits the role"}'
    )
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        gen = await step_generator.generate_step(
            talent={"name": "T"},
            contact={"name": "C", "decision_role": "buyer"},
            brand={"name": "B"},
            step=_step(),
            template=_template(),
            candidate_angles=[{"angle": _angle("ang_1"), "merge_fields": {}, "score": 0.7}],
        )
    assert gen.subject == "Quick intro"
    assert gen.body == "Hi there, want to chat?"
    assert gen.angles_used["primary"] == "ang_1"
    assert gen.validation_warnings == []
    assert gen.model_used == "claude-haiku-4-5"


@pytest.mark.asyncio
async def test_unit__step_generator__retries_on_validation_failure() -> None:
    """First response too long; second response passes."""
    bad = _llm_response(
        '{"subject": "ok", "body": "' + ("x" * 800) + '", '
        '"angles_used": {"primary": "ang_1"}, '
        '"personalization_fields_used": [], "reasoning": "x"}'
    )
    good = _llm_response(
        '{"subject": "ok", "body": "short body", '
        '"angles_used": {"primary": "ang_1"}, '
        '"personalization_fields_used": [], "reasoning": "x"}'
    )
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=[bad, good])
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        gen = await step_generator.generate_step(
            talent={"name": "T"},
            contact={"name": "C", "decision_role": "buyer"},
            brand={"name": "B"},
            step=_step(),
            template=_template(),
            candidate_angles=[{"angle": _angle("ang_1"), "merge_fields": {}, "score": 0.7}],
        )
    assert gen.body == "short body"
    assert gen.validation_warnings == []
    assert client.messages.create.await_count == 2


@pytest.mark.asyncio
async def test_unit__step_generator__llm_error_failsoft() -> None:
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=RuntimeError("LLM down"))
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        gen = await step_generator.generate_step(
            talent={"name": "T"},
            contact={"name": "C", "decision_role": "buyer"},
            brand={"name": "B"},
            step=_step(),
            template=_template(),
            candidate_angles=[],
        )
    assert gen.subject == ""
    assert gen.body == ""
    assert any("llm_error" in w for w in gen.validation_warnings)


@pytest.mark.asyncio
async def test_unit__step_generator__banned_phrase_flagged() -> None:
    """Banned phrases are listed but the step is still kept (warnings only)."""
    bad_then_good = [
        _llm_response(
            '{"subject": "Hi", "body": "I hope this email finds you well. '
            'Quick intro...", "angles_used": {"primary": "ang_1"}, '
            '"personalization_fields_used": [], "reasoning": "x"}'
        )
    ] * 3  # all 3 attempts hit the banned phrase
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=bad_then_good)
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        gen = await step_generator.generate_step(
            talent={"name": "T"},
            contact={"name": "C", "decision_role": "buyer"},
            brand={"name": "B"},
            step=_step(),
            template=_template(),
            candidate_angles=[{"angle": _angle("ang_1"), "merge_fields": {}, "score": 0.7}],
        )
    # We still return the LAST parsed response (with warnings); the caller sees the warning.
    assert any("banned_phrase" in w for w in gen.validation_warnings)


@pytest.mark.asyncio
async def test_unit__step_generator__hallucinated_angle_flagged() -> None:
    """LLM returns an angle_id not in the candidate set → flagged."""
    response = _llm_response(
        '{"subject": "ok", "body": "short", '
        '"angles_used": {"primary": "not_in_set"}, '
        '"personalization_fields_used": [], "reasoning": "x"}'
    )
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    with patch("app.agents.llm_client.get_async_anthropic", return_value=client):
        gen = await step_generator.generate_step(
            talent={"name": "T"},
            contact={"name": "C", "decision_role": "buyer"},
            brand={"name": "B"},
            step=_step(),
            template=_template(),
            candidate_angles=[{"angle": _angle("ang_1"), "merge_fields": {}, "score": 0.7}],
        )
    assert any("angle_not_in_candidates" in w for w in gen.validation_warnings)


def test_unit__step_generator__parse_response_strips_code_fences() -> None:
    parsed = step_generator._parse_response(  # pyright: ignore[reportPrivateUsage]
        '```json\n{"subject": "ok"}\n```'
    )
    assert parsed == {"subject": "ok"}


def test_unit__step_generator__parse_response_invalid_returns_none() -> None:
    assert step_generator._parse_response("totally not json") is None  # pyright: ignore[reportPrivateUsage]
