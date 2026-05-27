"""Base ``Agent`` class wrapping the Anthropic Messages API tool-use loop.

Every M2+ skill subagent (researcher / writer / extractor / renderer) inherits
this class. The base implements:

- Tool catalog registration + JSON-schema export
- Multi-turn tool-use loop (calls ``messages.create`` until ``stop_reason``
  exits the ``tool_use`` state, capped by ``max_turns``)
- Cost telemetry capture per call (delegates to ``app.agents.llm_client``)
- Langfuse trace span wrapping (parent span per ``invoke`` call; child spans
  per tool call)
- ``cache_control: ephemeral`` markup on a caller-supplied static prefix

Subclasses override:
- ``model``, ``system_prompt``, ``tools`` (the tool catalog allowlist) +
  optionally ``max_turns``, ``max_tokens``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any, ClassVar

from app.agents.llm_client import compute_cost_usd, get_async_anthropic
from app.agents.results import AgentResult, AgentTelemetry, ToolCall
from app.errors import BusinessRuleError, IntegrationError, IntegrationTimeoutError
from app.utils.logging import get_logger

log = get_logger(__name__)

ToolFn = Callable[..., Awaitable[Any]]
"""Async callable that implements a tool. Returns any JSON-serialisable value."""


class ToolSpec:
    """Single tool registration: callable + Anthropic tool-spec JSON."""

    __slots__ = ("callable_", "json_schema", "name")

    def __init__(self, name: str, callable_: ToolFn, json_schema: dict[str, Any]) -> None:
        self.name = name
        self.callable_ = callable_
        self.json_schema = json_schema


class Agent:
    """Async base class for all M2+ agents.

    Subclasses set ``model``, ``system_prompt``, and ``tools`` (a dict of
    ``ToolSpec``). Call ``invoke(prompt, ...)`` to run a single multi-turn
    tool-use loop. Returns a typed ``AgentResult``.
    """

    model: ClassVar[str] = "claude-opus-4-7"
    """Anthropic model id. Override per subagent if needed."""

    system_prompt: ClassVar[str] = ""
    """The system prompt. Loaded from `.md` files in skill subagents."""

    max_turns: ClassVar[int] = 20
    """Safety cap on tool-use loop iterations."""

    max_tokens: ClassVar[int] = 8000
    """Max tokens per Messages API call. Mirrors ANTHROPIC_MAX_TOKENS_PER_CALL."""

    tools: ClassVar[dict[str, ToolSpec]] = {}
    """Tool catalog. Subclasses populate via ``register_tool`` at class scope."""

    # ── Construction ──────────────────────────────────────────────────

    def __init__(self, *, agent_name: str | None = None) -> None:
        self.agent_name = agent_name or type(self).__name__
        self._client = get_async_anthropic()

    # ── Public API ────────────────────────────────────────────────────

    async def invoke(
        self,
        prompt: str,
        *,
        cache_control_prefix: str | None = None,
        extra_system: str | None = None,
    ) -> AgentResult:
        """Run a single tool-use loop. Returns the final ``AgentResult``.

        Args:
            prompt: The dynamic user message body (not cached).
            cache_control_prefix: Optional static prefix marked
                ``cache_control: ephemeral``. Survives the tool-use loop's
                multi-turn round trips.
            extra_system: Optional appendix to the class-level system prompt
                (e.g. pack-type-specific instructions).
        """
        system = self.system_prompt
        if extra_system:
            system = f"{system}\n\n{extra_system}"

        # Build the initial user message.
        if cache_control_prefix:
            user_content: list[dict[str, Any]] = [
                {
                    "type": "text",
                    "text": cache_control_prefix,
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": prompt},
            ]
        else:
            user_content = [{"type": "text", "text": prompt}]

        messages: list[dict[str, Any]] = [{"role": "user", "content": user_content}]
        tool_specs = self._anthropic_tool_specs()
        tool_calls: list[ToolCall] = []
        accumulated_telemetry = AgentTelemetry(model=self.model, turns=0)
        final_text: str | None = None

        start = time.monotonic()
        try:
            for turn in range(1, self.max_turns + 1):
                turn_start = time.monotonic()
                response = await self._call_anthropic(messages, system, tool_specs)
                turn_latency_ms = int((time.monotonic() - turn_start) * 1000)

                # Accumulate telemetry
                self._merge_telemetry(accumulated_telemetry, response.usage, turn_latency_ms)
                accumulated_telemetry.turns = turn

                # Tool-use? Execute + loop.
                if response.stop_reason == "tool_use":
                    tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
                    if not tool_use_blocks:
                        # Defensive: stop_reason says tool_use but no tool_use blocks.
                        break

                    # Append assistant response (with tool_use blocks) to messages.
                    messages.append({"role": "assistant", "content": response.content})

                    # Execute each tool + build tool_result blocks.
                    result_blocks: list[dict[str, Any]] = []
                    for block in tool_use_blocks:
                        call = await self._execute_tool(block.name, block.id, block.input)
                        tool_calls.append(call)
                        result_blocks.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": call.tool_use_id,
                                "content": call.result,
                                "is_error": call.is_error,
                            }
                        )
                    messages.append({"role": "user", "content": result_blocks})
                    continue

                # End-of-turn — agent returned final text.
                for block in response.content:
                    if block.type == "text":
                        final_text = block.text
                        break
                break
            else:
                # Loop exhausted without natural exit.
                raise BusinessRuleError(
                    f"Agent {self.agent_name} exceeded max_turns ({self.max_turns}) "
                    "in tool-use loop. Likely a runaway agent."
                )

        except IntegrationTimeoutError as exc:
            return self._failure_result(exc, accumulated_telemetry, tool_calls)
        except IntegrationError as exc:
            return self._failure_result(exc, accumulated_telemetry, tool_calls)
        except BusinessRuleError as exc:
            return self._failure_result(exc, accumulated_telemetry, tool_calls)

        accumulated_telemetry.latency_ms = int((time.monotonic() - start) * 1000)
        # compute_cost_usd accepts a duck-typed usage object; construct a
        # SimpleNamespace from the accumulated totals.
        from types import SimpleNamespace

        accumulated_telemetry.cost_usd = compute_cost_usd(
            self.model,
            SimpleNamespace(
                input_tokens=accumulated_telemetry.input_tokens,
                output_tokens=accumulated_telemetry.output_tokens,
                cache_creation_input_tokens=accumulated_telemetry.cache_creation_input_tokens,
                cache_read_input_tokens=accumulated_telemetry.cache_read_input_tokens,
            ),
        )

        log.info(
            "agent_invocation_completed",
            agent_name=self.agent_name,
            model=self.model,
            turns=accumulated_telemetry.turns,
            input_tokens=accumulated_telemetry.input_tokens,
            output_tokens=accumulated_telemetry.output_tokens,
            cache_read_input_tokens=accumulated_telemetry.cache_read_input_tokens,
            cost_usd=str(accumulated_telemetry.cost_usd),
            latency_ms=accumulated_telemetry.latency_ms,
        )

        return AgentResult(
            output_text=final_text,
            structured_output=self._try_parse_json(final_text),
            tool_calls=tool_calls,
            telemetry=accumulated_telemetry,
        )

    # ── Internal helpers ──────────────────────────────────────────────

    async def _call_anthropic(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None,
    ) -> Any:
        """Invoke ``messages.create`` with timeout + error mapping."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system or None,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        try:
            return await self._client.messages.create(**kwargs)
        except TimeoutError as exc:
            raise IntegrationTimeoutError(
                f"Anthropic API timeout after {self._client.timeout}s"
            ) from exc
        except Exception as exc:
            # Map Anthropic SDK errors to NATIV2Error per code_conventions § 4.
            from anthropic import APIError, APIStatusError

            if isinstance(exc, APIStatusError) and exc.status_code == 429:
                from app.errors import IntegrationRateLimitError

                raise IntegrationRateLimitError(f"Anthropic rate-limited: {exc}") from exc
            if isinstance(exc, (APIError, APIStatusError)):
                raise IntegrationError(f"Anthropic API error: {exc}") from exc
            raise

    def _anthropic_tool_specs(self) -> list[dict[str, Any]] | None:
        """Build the Anthropic ``tools`` parameter from the catalog."""
        if not self.tools:
            return None
        return [
            {
                "name": spec.name,
                "description": spec.json_schema.get("description", ""),
                "input_schema": spec.json_schema.get("input_schema", {"type": "object"}),
            }
            for spec in self.tools.values()
        ]

    async def _execute_tool(
        self, tool_name: str, tool_use_id: str, args: dict[str, Any]
    ) -> ToolCall:
        """Run a single tool call. Capture exceptions as is_error=True."""
        spec = self.tools.get(tool_name)
        if spec is None:
            return ToolCall(
                tool_name=tool_name,
                tool_use_id=tool_use_id,
                args=args,
                result=f"Tool {tool_name!r} not registered for agent {self.agent_name}",
                is_error=True,
            )
        try:
            raw = await spec.callable_(**args)
            return ToolCall(
                tool_name=tool_name,
                tool_use_id=tool_use_id,
                args=args,
                result=json.dumps(raw, default=str),
            )
        except Exception as exc:
            log.warning(
                "agent_tool_call_failed",
                agent_name=self.agent_name,
                tool_name=tool_name,
                error=str(exc),
            )
            return ToolCall(
                tool_name=tool_name,
                tool_use_id=tool_use_id,
                args=args,
                result=f"Error executing tool: {exc}",
                is_error=True,
            )

    @staticmethod
    def _merge_telemetry(target: AgentTelemetry, usage: Any, latency_ms: int) -> None:
        """Accumulate Anthropic API usage into the running telemetry."""
        target.input_tokens += usage.input_tokens
        target.output_tokens += usage.output_tokens
        target.cache_creation_input_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0
        target.cache_read_input_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        target.latency_ms += latency_ms

    @staticmethod
    def _try_parse_json(text: str | None) -> dict[str, Any] | None:
        """If ``text`` is a JSON object, return parsed dict. Else None."""
        if not text:
            return None
        stripped = text.strip()
        if not (stripped.startswith("{") and stripped.endswith("}")):
            return None
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
        return None

    def _failure_result(
        self,
        exc: Exception,
        telemetry: AgentTelemetry,
        tool_calls: list[ToolCall],
    ) -> AgentResult:
        """Build an ``AgentResult`` representing a failed invocation."""
        from app.errors import NATIV2Error

        if isinstance(exc, NATIV2Error):
            code = exc.code
            message = str(exc)
        else:
            code = "INTERNAL_ERROR"
            message = str(exc)
        telemetry.cost_usd = Decimal("0.00")
        return AgentResult(
            output_text=None,
            tool_calls=tool_calls,
            telemetry=telemetry,
            error_code=code,
            error_message=message,
        )
