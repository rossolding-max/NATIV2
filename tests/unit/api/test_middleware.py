"""Hardening tests for ``RequestContextMiddleware``.

Covers: header generation, honouring inbound ``X-Request-Id``, and isolation
between concurrent requests.
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from structlog.contextvars import get_contextvars

from app.api.middleware import RequestContextMiddleware


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/echo-request-id")
    async def _echo(_request: Request) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        ctx = get_contextvars()
        return {"request_id": str(ctx.get("request_id", ""))}

    return app


async def test_unit__middleware_generates_request_id_when_absent() -> None:
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/echo-request-id")
    assert r.status_code == 200
    body = r.json()
    assert body["request_id"].startswith("req_")
    # Header echoed back to the client.
    assert r.headers["X-Request-Id"] == body["request_id"]


async def test_unit__middleware_honours_inbound_x_request_id() -> None:
    app = _make_app()
    custom = "req_custom_idempotency_key"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/echo-request-id", headers={"X-Request-Id": custom})
    assert r.status_code == 200
    assert r.json()["request_id"] == custom
    assert r.headers["X-Request-Id"] == custom


async def test_unit__middleware_request_ids_isolated_between_concurrent_requests() -> None:
    """100 concurrent GETs each return a distinct request_id (no leakage)."""
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        responses = await asyncio.gather(*(c.get("/echo-request-id") for _ in range(100)))
    ids = {r.json()["request_id"] for r in responses}
    assert len(ids) == 100, f"context bleed: {100 - len(ids)} duplicate ids"
