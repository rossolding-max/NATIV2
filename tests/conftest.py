"""Pytest fixtures shared across the test tree.

Two layers:

1. **Always-available fixtures** — no Docker required. ``app_client_minimal``
   builds a FastAPI test client without the lifespan-ping pings, so unit-flavoured
   tests can exercise the request envelope cheaply.

2. **Service-backed fixtures** (testcontainers) — boot Postgres + Redis + MinIO.
   Used by ``tests/integration/`` and automatically skip the test if Docker is
   not reachable. Honours the ``TESTCONTAINERS_DOCKER_AVAILABLE`` env var as an
   explicit opt-out for CI environments without Docker.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

# ── Always-available fixtures ─────────────────────────────────────────


@pytest.fixture
def synthetic_agency_profile() -> dict[str, object]:
    """The minimal Acme agency_profile fixture used by lightweight tests.

    Full Acme content lands progressively in M4 alongside the real agency_setup
    workflow.
    """
    path = Path(__file__).parent / "fixtures" / "synthetic" / "agency_profile.json"
    return json.loads(path.read_text())


@pytest.fixture
async def app_client_minimal() -> AsyncGenerator[AsyncClient, None]:
    """FastAPI test client that actually runs the app's lifespan.

    Running the lifespan means ``app.state.service_status`` is populated (the
    ping helpers run; postgres / minio likely return "down" if those services
    aren't up, but the keys are present which is what the smoke tests assert).
    """
    from app.main import app

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


# ── Service-backed fixtures (testcontainers) ──────────────────────────


def _docker_available() -> bool:
    """Return True if Docker is installed AND reachable.

    Two-stage check: binary on PATH first, then ``docker info`` to confirm the
    daemon answers. testcontainers' own probe surfaces cryptic errors otherwise.
    """
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


@pytest.fixture(scope="session")
def _docker_check() -> None:  # pyright: ignore[reportUnusedFunction]
    """Skip the test session's service-backed fixtures if Docker isn't reachable.

    Other session fixtures depend on this via fixture injection; pyright cannot
    see the indirect usage.
    """
    if not _docker_available():
        pytest.skip(
            "Docker not available — skipping testcontainers-backed integration tests. "
            "Install Docker Desktop and ensure the daemon is running."
        )


@pytest.fixture(scope="session")
def postgres_container(_docker_check: None) -> Generator[object, None, None]:
    """Session-scoped Postgres 16 container with pgcrypto installed."""
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

    container = PostgresContainer("postgres:16-alpine")
    container.start()
    try:
        # Enable pgcrypto on the test DB.
        import psycopg  # type: ignore[import-not-found]

        with psycopg.connect(container.get_connection_url().replace("+psycopg2", "")) as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
            conn.commit()
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def redis_container(_docker_check: None) -> Generator[object, None, None]:
    """Session-scoped Redis 7 container."""
    from testcontainers.redis import RedisContainer  # type: ignore[import-untyped]

    container = RedisContainer("redis:7-alpine")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def minio_container(_docker_check: None) -> Generator[object, None, None]:
    """Session-scoped MinIO container."""
    from testcontainers.minio import MinioContainer  # type: ignore[import-untyped]

    container = MinioContainer()
    container.start()
    try:
        yield container
    finally:
        container.stop()
