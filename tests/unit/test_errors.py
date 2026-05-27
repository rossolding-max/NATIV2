"""Hardening tests for the ``NATIV2Error`` hierarchy + the FastAPI handler.

Verifies that every documented subclass surfaces the correct HTTP status,
error code, and envelope shape per ``docs/api_conventions.md`` § 3.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.api.middleware import RequestContextMiddleware
from app.api.responses import APIError, APIResponse, make_meta
from app.errors import (
    AuthorizationError,
    BusinessRuleError,
    ConflictError,
    DegradedModeError,
    IdempotencyMismatchError,
    IntegrationError,
    IntegrationRateLimitError,
    IntegrationTimeoutError,
    NATIV2Error,
    NotFoundError,
    OptimisticLockError,
    ValidationError,
)


def _make_test_app() -> FastAPI:
    """Build a test FastAPI app wiring only the bits under test."""
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.exception_handler(NATIV2Error)
    async def _h(_request: object, exc: NATIV2Error) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        body = APIResponse[object](
            data=None,
            meta=make_meta(),
            errors=[
                APIError(
                    code=exc.code,
                    message=str(exc),
                    field=exc.field,
                    detail=exc.detail or None,
                )
            ],
        )
        return JSONResponse(status_code=exc.http_status, content=body.model_dump(mode="json"))

    router = APIRouter()

    @router.get("/raise/{name}")
    async def _raise(name: str) -> object:  # pyright: ignore[reportUnusedFunction]
        mapping: dict[str, type[NATIV2Error]] = {
            "validation": ValidationError,
            "business": BusinessRuleError,
            "not_found": NotFoundError,
            "conflict": ConflictError,
            "optimistic_lock": OptimisticLockError,
            "idempotency_mismatch": IdempotencyMismatchError,
            "auth": AuthorizationError,
            "integration": IntegrationError,
            "integration_timeout": IntegrationTimeoutError,
            "integration_rate_limit": IntegrationRateLimitError,
            "degraded": DegradedModeError,
        }
        cls = mapping[name]
        raise cls(f"raised: {name}")

    app.include_router(router)
    return app


@pytest.mark.parametrize(
    ("name", "expected_status", "expected_code"),
    [
        ("validation", 422, "VALIDATION_ERROR"),
        ("business", 422, "BUSINESS_RULE_ERROR"),
        ("not_found", 404, "NOT_FOUND"),
        ("conflict", 409, "CONFLICT"),
        ("optimistic_lock", 409, "OPTIMISTIC_LOCK_ERROR"),
        ("idempotency_mismatch", 409, "IDEMPOTENCY_MISMATCH"),
        ("auth", 403, "AUTHORIZATION_ERROR"),
        ("integration", 502, "INTEGRATION_ERROR"),
        ("integration_timeout", 502, "INTEGRATION_TIMEOUT"),
        ("integration_rate_limit", 429, "INTEGRATION_RATE_LIMIT"),
        ("degraded", 503, "DEGRADED_MODE"),
    ],
)
async def test_unit__error_handler_maps_to_envelope(
    name: str, expected_status: int, expected_code: str
) -> None:
    app = _make_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/raise/{name}")
    assert r.status_code == expected_status
    body = r.json()
    assert body["data"] is None
    assert body["errors"][0]["code"] == expected_code
    assert body["errors"][0]["message"].startswith("raised: ")
    assert body["meta"]["api_version"] == "v1"
    assert body["meta"]["request_id"].startswith("req_")


def test_unit__error_hierarchy_inheritance() -> None:
    """Hierarchy mirrors the doc; clients can catch the parent class."""
    assert issubclass(OptimisticLockError, ConflictError)
    assert issubclass(IdempotencyMismatchError, ConflictError)
    assert issubclass(IntegrationTimeoutError, IntegrationError)
    assert issubclass(IntegrationRateLimitError, IntegrationError)
    for cls in (
        ValidationError,
        BusinessRuleError,
        NotFoundError,
        ConflictError,
        AuthorizationError,
        IntegrationError,
        DegradedModeError,
    ):
        assert issubclass(cls, NATIV2Error)


def test_unit__error_carries_field_and_detail() -> None:
    """Optional ``field`` + ``detail`` propagate through the constructor."""
    err = ValidationError("bad", field="email", detail={"reason": "format"})
    assert err.field == "email"
    assert err.detail == {"reason": "format"}
    assert err.code == "VALIDATION_ERROR"
    assert err.http_status == 422
