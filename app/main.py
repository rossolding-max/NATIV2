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
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import agencies as agencies_router
from app.api import brand_candidates as brand_candidates_router
from app.api import brand_contacts as brand_contacts_router
from app.api import brand_deals as brand_deals_router
from app.api import deals as deals_router
from app.api import enrollments as enrollments_router
from app.api import talents as talents_router
from app.api.middleware import RequestContextMiddleware
from app.api.responses import APIError, APIResponse, make_meta
from app.api.webhooks import oauth_callbacks as oauth_callbacks_router
from app.api.webhooks import smartlead as smartlead_webhook_router
from app.config import settings
from app.db.session import async_session_factory, engine
from app.errors import NATIV2Error
from app.observability.langfuse import init_langfuse
from app.observability.sentry import init_sentry
from app.utils.logging import get_logger, init_logging
from app.utils.taxonomies import init_taxonomies

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


async def _try_load_singleton_agency() -> tuple[UUID | None, str | None]:
    """Read the singleton ``agency_id`` + first ``agent_id`` from Postgres.

    At M0 the ``agency_profile`` table does not exist yet; this function
    returns ``(None, None)`` and the caller logs accordingly. Post-M1 +
    pre-M4 the table exists but is empty — also returns ``(None, None)``.
    Post-M4 either returns the (agency_id, agent_id) tuple or logs an
    error on the multiple-row state.
    """
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                text("SELECT agency_id, data FROM agency_profile LIMIT 2")
            )
            rows = result.fetchall()
    except Exception as exc:
        log.info("agency_singleton_skipped", reason=str(exc))
        return None, None

    if len(rows) == 0:
        log.info("agency_singleton_absent", note="phase_0_setup_required")
        return None, None
    if len(rows) > 1:
        log.error("agency_singleton_multiple_rows", count=len(rows))
        return None, None

    agency_id_raw, data_blob = rows[0][0], rows[0][1] or {}
    agency_uuid = agency_id_raw if isinstance(agency_id_raw, UUID) else UUID(str(agency_id_raw))
    agents = data_blob.get("agents") or []
    agent_id = agents[0].get("agent_id") if agents else None
    log.info("agency_singleton_loaded", agency_id=str(agency_uuid), agent_id=agent_id)
    return agency_uuid, agent_id


# ── Lifespan ─────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Boot dependencies in the documented order."""
    init_sentry()
    init_logging()
    init_langfuse()

    # Load static reference taxonomies (niches, industries, affinities, IAB,
    # competitors). Best-effort: if data files are absent, the app still boots
    # but `/health` surfaces `taxonomies: "down"`.
    taxonomies_status = "ok"
    try:
        init_taxonomies()
    except Exception as exc:
        log.warning("taxonomies_load_failed", error=str(exc))
        taxonomies_status = "down"

    app.state.service_status = {
        "postgres": await _ping_postgres(),
        "redis": await _ping_redis(),
        "minio": await _ping_minio(),
        "langfuse": "ok" if settings.langfuse_enabled else "disabled",
        "taxonomies": taxonomies_status,
    }

    # Best-effort singleton load. agency_id stays None at M0 (table absent)
    # and post-M1 pre-M4 (table empty); post-M4 it binds to the row.
    agency_uuid, agent_id = await _try_load_singleton_agency()
    app.state.agency_id = agency_uuid
    app.state.agent_id = agent_id

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
app.include_router(agencies_router.router, prefix="/api/v1")
app.include_router(talents_router.router, prefix="/api/v1")
app.include_router(oauth_callbacks_router.router, prefix="/api/v1")
app.include_router(brand_deals_router.talent_scoped_router, prefix="/api/v1")
app.include_router(brand_deals_router.top_level_router, prefix="/api/v1")
app.include_router(brand_candidates_router.talent_scoped_router, prefix="/api/v1")
app.include_router(brand_candidates_router.top_level_router, prefix="/api/v1")
app.include_router(brand_candidates_router.discovery_router, prefix="/api/v1")
app.include_router(brand_contacts_router.brand_scoped_router, prefix="/api/v1")
app.include_router(brand_contacts_router.talent_scoped_router, prefix="/api/v1")
app.include_router(brand_contacts_router.top_level_router, prefix="/api/v1")
app.include_router(enrollments_router.brand_scoped_router, prefix="/api/v1")
app.include_router(enrollments_router.talent_scoped_router, prefix="/api/v1")
app.include_router(enrollments_router.top_level_router, prefix="/api/v1")
app.include_router(deals_router.brand_scoped_router, prefix="/api/v1")
app.include_router(deals_router.talent_scoped_router, prefix="/api/v1")
app.include_router(deals_router.top_level_router, prefix="/api/v1")
app.include_router(smartlead_webhook_router.router, prefix="/api/v1")


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
