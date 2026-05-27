"""FastAPI application + lifespan + ``/health`` endpoint.

Boot order in lifespan (matters):

1. ``init_sentry()`` — first, so subsequent log events attach as breadcrumbs.
2. ``init_logging()`` — structlog config.
3. ``init_langfuse()`` — LLM trace observability.
4. Service pings (postgres, redis, minio) — best-effort; lifespan does not
   refuse to start if a dep is down (the ``/health`` endpoint surfaces the
   status to the caller instead).
5. Singleton ``agency_id`` load — best-effort (``app.state.agency_id``).

The exception handler converts ``NATIV2Error`` → enveloped JSON per
``docs/api_conventions.md``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.middleware import RequestContextMiddleware
from app.api.responses import APIError, APIResponse, make_meta
from app.config import settings
from app.db.session import async_session_factory, engine
from app.errors import NATIV2Error
from app.observability.langfuse import init_langfuse
from app.observability.sentry import init_sentry
from app.utils.logging import get_logger, init_logging

log = get_logger(__name__)


# ── Service ping helpers ─────────────────────────────────────────────


async def _ping_postgres() -> str:
    """Return ``"ok"`` if Postgres answers ``SELECT 1``, else ``"down"``."""
    try:
        async with async_session_factory() as session:
            await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=5.0)
        return "ok"
    except Exception as exc:
        log.warning("postgres_ping_failed", error=str(exc))
        return "down"


async def _ping_redis() -> str:
    """Return ``"ok"`` if Redis ``PING`` succeeds, else ``"down"``."""
    try:
        import redis.asyncio as aioredis  # type: ignore[import-untyped]

        url = settings.celery_broker_url
        client = aioredis.from_url(url)
        try:
            await asyncio.wait_for(client.ping(), timeout=5.0)
            return "ok"
        finally:
            await client.aclose()
    except Exception as exc:
        log.warning("redis_ping_failed", error=str(exc))
        return "down"


async def _ping_minio() -> str:
    """Return ``"ok"`` if MinIO health endpoint responds, else ``"down"``."""
    try:
        import httpx

        url = str(settings.s3_endpoint_url).rstrip("/") + "/minio/health/ready"
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url)
            return "ok" if r.status_code == 200 else "down"
    except Exception as exc:
        log.warning("minio_ping_failed", error=str(exc))
        return "down"


async def _try_load_singleton_agency() -> None:
    """Read the singleton ``agency_id`` from Postgres if the table exists.

    At M0 the ``agency_profile`` table does not exist yet (lands in M1); this
    function logs a warning and leaves ``app.state.agency_id`` as ``None``.
    Post-M1 it will either find one row (set the singleton) or raise on
    multiple-row state.
    """
    try:
        async with async_session_factory() as session:
            result = await session.execute(text("SELECT agency_id FROM agency_profile LIMIT 2"))
            rows = result.fetchall()
    except Exception as exc:
        log.info("agency_singleton_skipped", reason=str(exc))
        return

    if len(rows) == 0:
        log.info("agency_singleton_absent", note="phase_0_setup_required")
    elif len(rows) > 1:
        log.error("agency_singleton_multiple_rows", count=len(rows))
    else:
        # Bind the singleton when found. The app.state mutation happens in
        # lifespan() since we don't hold a reference to the FastAPI app here.
        log.info("agency_singleton_loaded", agency_id=str(rows[0][0]))


# ── Lifespan ─────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Boot dependencies in the documented order."""
    init_sentry()
    init_logging()
    init_langfuse()

    app.state.service_status = {
        "postgres": await _ping_postgres(),
        "redis": await _ping_redis(),
        "minio": await _ping_minio(),
        "langfuse": "ok" if settings.langfuse_enabled else "disabled",
    }

    # Best-effort singleton load. agency_id stays None at M0 (table absent).
    app.state.agency_id = None
    app.state.agent_id = None
    await _try_load_singleton_agency()

    log.info(
        "app_started",
        environment=settings.nativ2_environment,
        version=settings.nativ2_version,
        bind=f"{settings.nativ2_bind_host}:{settings.nativ2_bind_port}",
        services=app.state.service_status,
    )

    try:
        yield
    finally:
        log.info("app_shutdown_begin")
        await engine.dispose()
        log.info("app_shutdown_complete")


# ── App + middleware + handlers ──────────────────────────────────────


app = FastAPI(
    title="NATIV2 API",
    version=settings.nativ2_version,
    description="AI influencer marketing assistant for talent agencies.",
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(RequestContextMiddleware)


@app.exception_handler(NATIV2Error)
async def _nativ2_error_handler(  # pyright: ignore[reportUnusedFunction]
    _request: Request, exc: NATIV2Error
) -> JSONResponse:
    """Convert ``NATIV2Error`` instances to enveloped JSON responses."""
    error = APIError(
        code=exc.code,
        message=str(exc),
        field=exc.field,
        detail=exc.detail or None,
    )
    body = APIResponse[Any](data=None, meta=make_meta(), errors=[error])
    return JSONResponse(
        status_code=exc.http_status,
        content=body.model_dump(mode="json"),
    )


# ── Routes ───────────────────────────────────────────────────────────


@app.get("/health", tags=["health"])
async def health(request: Request) -> APIResponse[dict[str, Any]]:
    """Service health envelope. Returns 200 even when services are degraded;
    callers inspect ``data.services`` for per-service status.
    """
    services = getattr(request.app.state, "service_status", {})
    overall = "ok" if all(v in ("ok", "disabled") for v in services.values()) else "degraded"
    return APIResponse[dict[str, Any]](
        data={
            "status": overall,
            "version": settings.nativ2_version,
            "environment": settings.nativ2_environment,
            "services": services,
        },
        meta=make_meta(),
        errors=[],
    )
