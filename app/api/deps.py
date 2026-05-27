"""FastAPI dependencies for per-request context. See ``docs/auth_and_authorization.md``.

v0.1 single-tenant: ``current_agency_id()`` returns the singleton loaded at
lifespan startup, or ``None`` if the table is absent (M0) / empty (post-M1
pre-Phase-0).

v2: same dependency signature, but the value comes from a JWT claim instead.
The repository layer's ``agency_id`` filter is the same on both sides.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Request


def current_agency_id(request: Request) -> UUID | None:
    """Return the singleton ``agency_id`` from ``app.state``, or ``None``.

    Callers that require a non-None ``agency_id`` (every M4+ endpoint) raise
    ``DegradedModeError`` themselves. M0 has no such endpoints; ``/health``
    works regardless.
    """
    value = getattr(request.app.state, "agency_id", None)
    return value if isinstance(value, UUID) else None


def current_agent_id(request: Request) -> str | None:
    """Return the singleton ``agent_id`` (first agent in the agency record).

    None at M0 since no ``agency_profile`` row exists yet.
    """
    value = getattr(request.app.state, "agent_id", None)
    return value if isinstance(value, str) else None
