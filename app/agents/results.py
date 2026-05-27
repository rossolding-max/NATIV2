"""Result + telemetry types for agent invocations.

Every Agent call returns an ``AgentResult``. Every pack-generation run returns a
``PackResult[T]`` where ``T`` is the pack-specific Pydantic model (e.g.
``DiscoveryPrepPack``). These types let M11+ pack milestones consume agent
output with full type safety + telemetry.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolCall(BaseModel):
    """Single tool invocation captured during an agent's tool-use loop."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    tool_use_id: str
    args: dict[str, Any]
    result: str  # JSON-serialised return value or error string
    is_error: bool = False


class AgentTelemetry(BaseModel):
    """Per-Agent.invoke() cost + token usage.

    Anthropic Messages API exposes 4 token counters; we record all 4. Cost is
    computed in ``app/agents/llm_client.py`` per the documented model pricing.
    """

    model_config = ConfigDict(extra="forbid")

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cost_usd: Decimal = Field(default_factory=lambda: Decimal("0.00"))
    latency_ms: int = 0
    langfuse_trace_id: str | None = None
    langfuse_span_id: str | None = None
    turns: int = 1  # Number of tool-use loop iterations


class AgentResult(BaseModel):
    """Return value of ``Agent.invoke()``.

    Carries the final text output, the tool-call audit trail, and telemetry.
    Successful results have ``output_text != None`` and ``error_code is None``.
    Failures have ``output_text == None`` and ``error_code`` set.
    """

    model_config = ConfigDict(extra="forbid")

    output_text: str | None = None
    structured_output: dict[str, Any] | None = None
    """If the agent returned a JSON object as its final text, parse it here."""

    tool_calls: list[ToolCall] = Field(default_factory=list)
    telemetry: AgentTelemetry

    error_code: str | None = None
    """The ``NATIV2Error.code`` if the invocation failed."""
    error_message: str | None = None


class PackTelemetry(BaseModel):
    """Pack-level telemetry. Aggregates all subagent + tool calls in a generation.

    Sums of underlying AgentTelemetry entries. Recorded on every pack run for
    cost visibility + Langfuse rollup.
    """

    model_config = ConfigDict(extra="forbid")

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cost_usd: Decimal = Field(default_factory=lambda: Decimal("0.00"))
    latency_ms: int = 0
    langfuse_trace_id: str | None = None
    subagent_invocations: int = 0
    tool_invocations: int = 0


class PackResult[PackT](BaseModel):
    """Result of a pack-generation run. ``PackT`` is the pack's Pydantic model.

    Carries:
    - ``status``: completed / partial / failed.
    - ``pack``: the typed pack content (None on failed runs).
    - Artefact paths (filesystem at v0.1; S3 keys deferred to M4).
    - Aggregated telemetry across all subagent + tool calls in the run.
    - On failure: structured error code + message (from ``NATIV2Error``).
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    status: Literal["completed", "partial", "failed"]
    pack: PackT | None = None
    pack_id: str | None = None
    version: int = 1
    artifacts: dict[str, str] = Field(default_factory=dict)
    """Artefact label to local path; e.g. ``{"briefing": "data/.../briefing.md"}``."""

    telemetry: PackTelemetry
    created_at: datetime = Field(
        default_factory=lambda: datetime.now()  # noqa: DTZ005 — pydantic default
    )

    error_code: str | None = None
    error_message: str | None = None
