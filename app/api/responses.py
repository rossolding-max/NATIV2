"""Standard API response envelope. See ``docs/api_conventions.md`` § 2.

Every endpoint returns ``{data, meta, errors}``. This module owns the helper
types and constructors so handlers don't reinvent the shape per route.
"""

from __future__ import annotations

from datetime import UTC, datetime
from math import ceil
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from structlog.contextvars import get_contextvars

API_VERSION: str = "v1"


class APIError(BaseModel):
    """Single error entry inside ``errors[]``."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    field: str | None = None
    detail: dict[str, Any] | None = None


class APIMeta(BaseModel):
    """``meta`` block. Pagination fields populated only on list endpoints."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    timestamp: datetime
    api_version: str = API_VERSION

    # Pagination (list endpoints only)
    page: int | None = None
    page_size: int | None = None
    total_count: int | None = None
    total_pages: int | None = None


class APIResponse[T](BaseModel):
    """Standard envelope. ``data`` is ``None`` on error responses."""

    model_config = ConfigDict(extra="forbid")

    data: T | None = None
    meta: APIMeta
    errors: list[APIError] = Field(default_factory=list[APIError])


def _current_request_id() -> str:
    """Pull ``request_id`` from the structlog context, falling back to a fresh UUID."""
    ctx = get_contextvars()
    value = ctx.get("request_id")
    if isinstance(value, str) and value:
        return value
    return f"req_{uuid4().hex}"


def make_meta(
    *,
    page: int | None = None,
    page_size: int | None = None,
    total_count: int | None = None,
) -> APIMeta:
    """Build an ``APIMeta`` populated from the active request context.

    Pass ``page`` / ``page_size`` / ``total_count`` for paginated endpoints;
    ``total_pages`` is computed.
    """
    total_pages: int | None = None
    if page is not None and page_size is not None and total_count is not None:
        total_pages = ceil(total_count / page_size) if page_size else 0

    return APIMeta(
        request_id=_current_request_id(),
        timestamp=datetime.now(UTC),
        api_version=API_VERSION,
        page=page,
        page_size=page_size,
        total_count=total_count,
        total_pages=total_pages,
    )
