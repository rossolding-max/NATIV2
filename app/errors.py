"""NATIV2 exception hierarchy. See ``docs/code_conventions.md`` § 4.

All app code raises subclasses of ``NATIV2Error``. The FastAPI exception
handler in ``app.main`` converts them to the envelope-shaped JSON response
documented in ``docs/api_conventions.md``.
"""

from __future__ import annotations

from typing import Any


class NATIV2Error(Exception):
    """Root of the application error hierarchy.

    Subclasses set:
    - ``code``: stable identifier used by clients (e.g. ``"VALIDATION_ERROR"``)
    - ``http_status``: HTTP response code
    - ``user_message``: human-readable message safe to surface
    """

    code: str = "INTERNAL_ERROR"
    http_status: int = 500
    user_message: str | None = None

    def __init__(
        self,
        message: str | None = None,
        *,
        field: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or self.user_message or self.code)
        self.field = field
        self.detail = detail or {}


class ValidationError(NATIV2Error):
    """Input failed Pydantic validation or business-rule shape checks."""

    code = "VALIDATION_ERROR"
    http_status = 422


class BusinessRuleError(NATIV2Error):
    """Domain invariants violated (e.g. invalid state transition)."""

    code = "BUSINESS_RULE_ERROR"
    http_status = 422


class NotFoundError(NATIV2Error):
    """Resource not found in the agency scope."""

    code = "NOT_FOUND"
    http_status = 404


class ConflictError(NATIV2Error):
    """Conflict — concurrent edit, duplicate key, or similar."""

    code = "CONFLICT"
    http_status = 409


class OptimisticLockError(ConflictError):
    """Resource version mismatch on update (``If-Match`` ETag).

    v0.1 does not implement ``If-Match`` (per V2-API-01); the class exists
    so M2+ code can already raise it.
    """

    code = "OPTIMISTIC_LOCK_ERROR"


class IdempotencyMismatchError(ConflictError):
    """``Idempotency-Key`` reused with a different request body."""

    code = "IDEMPOTENCY_MISMATCH"


class AuthorizationError(NATIV2Error):
    """Caller is not authorised to perform the requested action.

    v0.1 has no auth (per ``docs/auth_and_authorization.md``); the class
    exists so M2+ gate code (commercial gate, legal review gate) can raise
    it without introducing the type later.
    """

    code = "AUTHORIZATION_ERROR"
    http_status = 403


class IntegrationError(NATIV2Error):
    """External vendor failure (Smartlead, Apollo, Meta, TikTok, etc.)."""

    code = "INTEGRATION_ERROR"
    http_status = 502


class IntegrationTimeoutError(IntegrationError):
    """Vendor call exceeded the configured timeout."""

    code = "INTEGRATION_TIMEOUT"


class IntegrationRateLimitError(IntegrationError):
    """Vendor returned a rate-limit response (HTTP 429 upstream)."""

    code = "INTEGRATION_RATE_LIMIT"
    http_status = 429


class DegradedModeError(NATIV2Error):
    """Service degraded — partial dependency outage.

    Raised when the platform can serve some endpoints but not the requested
    one (e.g. agency not initialised, vendor down hard).
    """

    code = "DEGRADED_MODE"
    http_status = 503
