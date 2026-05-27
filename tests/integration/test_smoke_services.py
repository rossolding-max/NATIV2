"""Smoke: testcontainers boot Postgres + Redis + MinIO and they answer pings.

These are the foundation tests M1+ relies on. If any of these fail, the whole
integration suite is unreliable.
"""

from __future__ import annotations

from typing import Any


def test_integration__postgres_container_reachable(postgres_container: Any) -> None:
    """Postgres answers ``SELECT 1`` and pgcrypto is installed."""
    import psycopg

    url = postgres_container.get_connection_url().replace("+psycopg2", "")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone() == (1,)
        cur.execute("SELECT extname FROM pg_extension WHERE extname='pgcrypto'")
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "pgcrypto"


def test_integration__redis_container_reachable(redis_container: Any) -> None:
    """Redis answers PING."""
    import redis

    client = redis.Redis(
        host=redis_container.get_container_host_ip(),
        port=int(redis_container.get_exposed_port(6379)),
    )
    try:
        assert client.ping() is True
    finally:
        client.close()


def test_integration__minio_container_reachable(minio_container: Any) -> None:
    """MinIO health endpoint returns 200."""
    import httpx

    host = minio_container.get_container_host_ip()
    port = int(minio_container.get_exposed_port(9000))
    url = f"http://{host}:{port}/minio/health/ready"

    r = httpx.get(url, timeout=5.0)
    assert r.status_code == 200
