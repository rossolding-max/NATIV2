"""Smoke: the FastAPI app boots and ``/health`` returns the documented envelope.

Replaces the PR 1 ``test_app_importable`` placeholder.
"""

from __future__ import annotations

import re

from httpx import AsyncClient


async def test_integration__health_returns_200_with_envelope(
    app_client_minimal: AsyncClient,
) -> None:
    """``/health`` returns 200 + the documented ``{data, meta, errors}`` envelope.

    Service status fields can be "ok" / "down" — that's fine for this test;
    test_integration__health_surfaces_service_status checks the specifics.
    """
    r = await app_client_minimal.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"data", "meta", "errors"}
    assert body["errors"] == []
    assert body["meta"]["api_version"] == "v1"
    assert re.match(r"^req_[0-9a-f]{32}$", body["meta"]["request_id"])
    assert body["data"]["version"] == "0.1.0"
    assert body["data"]["environment"] == "development"


async def test_integration__health_surfaces_per_service_status(
    app_client_minimal: AsyncClient,
) -> None:
    """``data.services`` includes postgres/redis/minio/langfuse/taxonomies keys."""
    r = await app_client_minimal.get("/health")
    services = r.json()["data"]["services"]
    assert set(services.keys()) >= {"postgres", "redis", "minio", "langfuse", "taxonomies"}
    # Each value must be one of the documented status strings.
    for value in services.values():
        assert value in ("ok", "degraded", "down", "disabled"), value
    # Taxonomies must load successfully (data files ship in `data/`).
    assert services["taxonomies"] == "ok"


async def test_integration__openapi_spec_advertises_correct_title(
    app_client_minimal: AsyncClient,
) -> None:
    """The OpenAPI spec carries the documented title + version."""
    r = await app_client_minimal.get("/openapi.json")
    spec = r.json()
    assert spec["info"]["title"] == "NATIV2 API"
    assert spec["info"]["version"] == "0.1.0"
    # /health must appear under paths.
    assert "/health" in spec["paths"]


async def test_integration__request_id_round_trips_via_header(
    app_client_minimal: AsyncClient,
) -> None:
    """An inbound ``X-Request-Id`` is honoured + echoed in the response header."""
    custom = "req_integration_smoke_id"
    r = await app_client_minimal.get("/health", headers={"X-Request-Id": custom})
    assert r.headers["X-Request-Id"] == custom
    assert r.json()["meta"]["request_id"] == custom
