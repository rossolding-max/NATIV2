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
    """Session-scoped Postgres 16 container with pgcrypto installed.

    Also re-binds ``app.config.settings`` to the testcontainer DSN. Without
    this rebind, every M0/M1 fixture's ``monkeypatch.setenv(POSTGRES_*)``
    + ``get_settings.cache_clear()`` pattern would still leave the
    already-imported module-level ``app.config.settings`` instance
    stale (with the default ``127.0.0.1:5432`` values that don't match
    the testcontainer's dynamic port). M3 + earlier hid this by skipping
    testcontainer-backed tests when Docker was unreachable; once Docker
    is available in CI, the pre-existing fixtures need the rebind to
    actually work.

    Direct attribute assignment (NOT ``monkeypatch.setattr``) so the
    binding persists for the whole session.
    """
    import re

    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

    container = PostgresContainer("postgres:16-alpine")
    container.start()
    try:
        # Enable pgcrypto on the test DB.
        import psycopg  # type: ignore[import-not-found]

        url = container.get_connection_url().replace("+psycopg2", "")
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
            conn.commit()

        match = re.match(
            r"postgresql(?:\+\w+)?://(?P<user>[^:]+):(?P<pw>[^@]+)@"
            r"(?P<host>[^:]+):(?P<port>\d+)/(?P<db>.+)",
            url,
        )
        if match is not None:
            from pydantic import SecretStr

            from app.config import settings as live_settings

            live_settings.postgres_user = match["user"]
            live_settings.postgres_password = SecretStr(match["pw"])
            live_settings.postgres_host = match["host"]
            live_settings.postgres_port = int(match["port"])
            live_settings.postgres_db = match["db"]

        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def redis_container(_docker_check: None) -> Generator[object, None, None]:
    """Session-scoped Redis 7 container.

    Also binds ``app.config.settings.redis_host`` + ``redis_port`` to the
    container's published address so the OAuth state store (M3, consumed
    by M5) and the rate limiter (M3) talk to the testcontainer instead
    of whatever Redis might be running on localhost:6379.
    """
    from testcontainers.redis import RedisContainer  # type: ignore[import-untyped]

    container = RedisContainer("redis:7-alpine")
    container.start()
    try:
        from app.config import settings as live_settings

        live_settings.redis_host = container.get_container_host_ip()
        live_settings.redis_port = int(container.get_exposed_port(6379))
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def minio_container(_docker_check: None) -> Generator[object, None, None]:
    """Session-scoped MinIO container.

    Also re-binds ``app.config.settings.s3_*`` to the testcontainer URL —
    same reasoning as the ``postgres_container`` rebind above.
    """
    from testcontainers.minio import MinioContainer  # type: ignore[import-untyped]

    container = MinioContainer()
    container.start()
    try:
        from pydantic import AnyHttpUrl, SecretStr

        from app.config import settings as live_settings

        cfg = container.get_config()
        live_settings.s3_endpoint_url = AnyHttpUrl(f"http://{cfg['endpoint']}")
        live_settings.s3_access_key = cfg["access_key"]
        live_settings.s3_secret_key = SecretStr(cfg["secret_key"])
        live_settings.s3_force_path_style = True

        yield container
    finally:
        container.stop()
