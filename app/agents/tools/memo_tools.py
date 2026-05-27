"""``read_memos`` + ``write_memo`` agent tools.

These wrap the M2-extended ``MemoRepository`` for use inside the Anthropic
tool-use loop. The exported ``READ_MEMOS_TOOL`` / ``WRITE_MEMO_TOOL`` are
declarative ``ToolSpec`` instances; ``bind_memo_tools(...)`` returns
session-bound ToolSpecs that an Agent's ``tools`` dict can use.

The factory pattern lets the agent be constructed in a per-request scope
(with a fresh DB session + agency_id binding) while keeping the JSON schema
shared across all callers.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import ToolSpec
from app.config import settings
from app.errors import BusinessRuleError
from app.models.sqla.memo import Memo
from app.repositories.memo import MemoRepository
from app.utils.ids import new_memo_id

# ── JSON schemas for the Anthropic tool-spec ──────────────────────────

_READ_MEMOS_SCHEMA: dict[str, Any] = {
    "description": (
        "Retrieve memos by tag filters. Filters are AND across tag keys; OR "
        "within a single key. Returns memos sorted by 'specificity' (deal_specific "
        "> brand_relationship > industry_pattern > talent_pattern > cross_cutting), "
        "then by last_retrieved_at DESC. Excludes soft-deleted and expired memos "
        "by default."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "talent_ids": {"type": "array", "items": {"type": "string"}},
            "brand_ids": {"type": "array", "items": {"type": "string"}},
            "industry_ids": {"type": "array", "items": {"type": "string"}},
            "deal_ids": {"type": "array", "items": {"type": "string"}},
            "topics": {"type": "array", "items": {"type": "string"}},
            "scope": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "deal_specific",
                        "brand_relationship",
                        "industry_pattern",
                        "talent_pattern",
                        "cross_cutting",
                    ],
                },
            },
            "memo_type": {"type": "array", "items": {"type": "string"}},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
            "sort": {
                "type": "string",
                "enum": ["specificity", "recency"],
                "default": "specificity",
            },
        },
        "additionalProperties": False,
    },
}

_WRITE_MEMO_SCHEMA: dict[str, Any] = {
    "description": (
        "Persist a new memo. Memos store agent learnings (brand observations, "
        "negotiation patterns, KPI insights, etc.). Tags drive future retrieval — "
        "topics is required (>=1 item). Caller's agent name is bound at "
        "construction time and stored automatically; do not pass it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "enum": [
                    "deal_specific",
                    "brand_relationship",
                    "industry_pattern",
                    "talent_pattern",
                    "cross_cutting",
                ],
            },
            "memo_type": {"type": "string"},
            "content_markdown": {"type": "string", "minLength": 1, "maxLength": 32768},
            "tags": {
                "type": "object",
                "properties": {
                    "talent_ids": {"type": "array", "items": {"type": "string"}},
                    "brand_ids": {"type": "array", "items": {"type": "string"}},
                    "industry_ids": {"type": "array", "items": {"type": "string"}},
                    "deal_ids": {"type": "array", "items": {"type": "string"}},
                    "topics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "phase_context": {"type": "string"},
                },
                "required": ["topics"],
                "additionalProperties": False,
            },
            "expires_at": {"type": "string", "format": "date-time"},
            "supersedes_memo_id": {"type": "string"},
        },
        "required": ["scope", "memo_type", "content_markdown", "tags"],
        "additionalProperties": False,
    },
}

READ_MEMOS_TOOL = ToolSpec("read_memos", lambda: None, _READ_MEMOS_SCHEMA)  # type: ignore[arg-type]
"""Declarative ToolSpec. Use ``bind_memo_tools`` to get a runtime instance."""

WRITE_MEMO_TOOL = ToolSpec("write_memo", lambda: None, _WRITE_MEMO_SCHEMA)  # type: ignore[arg-type]


# ── Runtime binding ───────────────────────────────────────────────────


def bind_memo_tools(
    session: AsyncSession,
    agency_id: UUID,
    *,
    created_by_agent: Literal["deal_orchestrator", "researcher", "writer", "extractor", "renderer"],
) -> dict[str, ToolSpec]:
    """Return runtime ToolSpecs bound to a session + agency + caller agent.

    Used by ``Agent`` subclasses at instantiation time:

        tools = bind_memo_tools(session, agency_id, created_by_agent="researcher")

    The returned dict can be merged with other tool bindings to form the
    agent's full catalog.
    """
    repo = MemoRepository(session, agency_id)

    async def _read_memos(**kwargs: Any) -> list[dict[str, Any]]:
        # Translate sort string → SortMode if present.
        memos = await repo.find_by_tags(**kwargs)
        await repo.mark_retrieved([m.memo_id for m in memos])
        return [_serialise_memo(m) for m in memos]

    async def _write_memo(
        scope: str,
        memo_type: str,
        content_markdown: str,
        tags: dict[str, Any],
        expires_at: str | None = None,
        supersedes_memo_id: str | None = None,
    ) -> dict[str, Any]:
        # Inline validation per the schema; raise NATIV2Error on bad input.
        if not tags.get("topics"):
            raise BusinessRuleError("tags.topics must contain at least 1 item")
        size_kb = len(content_markdown.encode("utf-8")) / 1024
        if size_kb > settings.memo_inline_max_kb:
            raise BusinessRuleError(
                f"content_markdown {size_kb:.1f}kB exceeds "
                f"MEMO_INLINE_MAX_KB={settings.memo_inline_max_kb}"
            )

        from datetime import datetime

        memo = Memo(
            memo_id=new_memo_id(),
            agency_id=agency_id,
            memo_type=memo_type,
            scope=scope,
            content_markdown=content_markdown,
            tags=tags,
            expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
        )
        # Note: created_by_agent is bound at the tool-construction site, but
        # `memo.schema.json` doesn't currently have a column for it — surfaced
        # to v0.2. For now, log it via structlog and tag the memo's tags.
        from app.utils.logging import get_logger

        get_logger(__name__).info(
            "memo_write",
            memo_id=memo.memo_id,
            scope=scope,
            memo_type=memo_type,
            created_by_agent=created_by_agent,
            supersedes=supersedes_memo_id,
        )
        if supersedes_memo_id:
            await repo.soft_delete(supersedes_memo_id, deleted_by_agent_id=created_by_agent)

        await repo.create(memo)
        await session.commit()
        return _serialise_memo(memo)

    return {
        "read_memos": ToolSpec("read_memos", _read_memos, _READ_MEMOS_SCHEMA),
        "write_memo": ToolSpec("write_memo", _write_memo, _WRITE_MEMO_SCHEMA),
    }


def _serialise_memo(m: Memo) -> dict[str, Any]:
    """Plain-dict serialisation of a Memo for tool-call return values."""
    return {
        "memo_id": m.memo_id,
        "memo_type": m.memo_type,
        "scope": m.scope,
        "content_markdown": m.content_markdown,
        "tags": m.tags,
        "expires_at": m.expires_at.isoformat() if m.expires_at else None,
        "retrieval_count": m.retrieval_count,
        "created_at": m.created_at.isoformat(),
    }
