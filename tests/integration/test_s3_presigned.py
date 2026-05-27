"""Integration tests for ``app.utils.s3`` against the MinIO testcontainer.

Confirms the presigned PUT URL accepts an actual PUT and the presigned GET
URL retrieves the same bytes.
"""

from __future__ import annotations

import contextlib
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
from pydantic import AnyHttpUrl, SecretStr

from app.config import settings as app_settings

_TEST_BUCKET = "m4-test-bucket"


@pytest.fixture
def _minio_bound(minio_container: Any, monkeypatch: pytest.MonkeyPatch) -> Any:  # pyright: ignore[reportUnusedFunction]
    """Point app settings at the testcontainer + create the bucket."""
    from app.utils import s3 as s3_util

    config = minio_container.get_config()
    # ``config['endpoint']`` is a string like ``127.0.0.1:32789``
    endpoint = f"http://{config['endpoint']}"

    monkeypatch.setattr(app_settings, "s3_endpoint_url", AnyHttpUrl(endpoint))
    monkeypatch.setattr(app_settings, "s3_access_key", config["access_key"])
    monkeypatch.setattr(app_settings, "s3_secret_key", SecretStr(config["secret_key"]))
    monkeypatch.setattr(app_settings, "s3_bucket", _TEST_BUCKET)
    monkeypatch.setattr(app_settings, "s3_force_path_style", True)

    s3_util.reset_client_for_tests()
    client = s3_util.get_s3_client()
    with contextlib.suppress(Exception):
        # Bucket may already exist on retry.
        client.create_bucket(Bucket=_TEST_BUCKET)

    yield

    s3_util.reset_client_for_tests()


@pytest.mark.usefixtures("_minio_bound")
async def test_integration__presigned_put__accepts_upload() -> None:
    from app.utils.s3 import generate_presigned_put_url

    key = "agency/test/branding/logo.png"
    url = generate_presigned_put_url(key=key, content_type="image/png")

    # Sanity-check URL shape.
    parsed = urlparse(url)
    assert parsed.scheme == "http"
    assert key in parsed.path

    payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    async with httpx.AsyncClient() as http:
        response = await http.put(url, content=payload, headers={"Content-Type": "image/png"})
    assert response.status_code == 200, response.text


@pytest.mark.usefixtures("_minio_bound")
async def test_integration__presigned_get__reads_uploaded_bytes() -> None:
    from app.utils.s3 import generate_presigned_get_url, generate_presigned_put_url

    key = "agency/test/branding/roundtrip.png"
    payload = b"hello-m4"

    put_url = generate_presigned_put_url(key=key, content_type="image/png")
    async with httpx.AsyncClient() as http:
        put_resp = await http.put(put_url, content=payload, headers={"Content-Type": "image/png"})
    assert put_resp.status_code == 200

    get_url = generate_presigned_get_url(key=key)
    async with httpx.AsyncClient() as http:
        get_resp = await http.get(get_url)
    assert get_resp.status_code == 200
    assert get_resp.content == payload
