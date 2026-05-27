"""S3 / MinIO helpers — lazy boto3 client + presigned-URL generators.

First consumer is M4 (Phase 0 agency-setup branding asset uploads); future
consumers include M11+ (artefact PDF persistence) + M14 (invoice PDFs).

Per CLAUDE.md: never read ``os.environ`` directly — settings come from
``app.config.settings``. Endpoint + access keys + bucket are all configured
there (defaults wired to local MinIO at ``http://127.0.0.1:9000``).

Client uses path-style addressing (required for MinIO) and is a module-level
singleton; reset via ``reset_client_for_tests()``.
"""

from __future__ import annotations

import boto3
from botocore.client import BaseClient
from botocore.config import Config as BotoConfig

from app.config import settings

_DEFAULT_PRESIGN_EXPIRES = 900

_client: BaseClient | None = None


def get_s3_client() -> BaseClient:
    """Return the lazy-initialised boto3 S3 client singleton."""
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=str(settings.s3_endpoint_url),
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            config=BotoConfig(
                s3={"addressing_style": "path" if settings.s3_force_path_style else "auto"},
                signature_version="s3v4",
            ),
        )
    return _client


def reset_client_for_tests() -> None:
    """Reset the singleton (test-only)."""
    global _client
    _client = None


def generate_presigned_put_url(
    *,
    key: str,
    content_type: str,
    bucket: str | None = None,
    expires_in: int = _DEFAULT_PRESIGN_EXPIRES,
) -> str:
    """Generate a single-use presigned PUT URL for uploading an object.

    Caller is responsible for binding the ``Content-Type`` header on the
    PUT request to match ``content_type`` — boto3 signs it into the URL.
    """
    client = get_s3_client()
    return client.generate_presigned_url(
        ClientMethod="put_object",
        Params={
            "Bucket": bucket or settings.s3_bucket,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
        HttpMethod="PUT",
    )


def generate_presigned_get_url(
    *,
    key: str,
    bucket: str | None = None,
    expires_in: int = _DEFAULT_PRESIGN_EXPIRES,
) -> str:
    """Generate a presigned GET URL for downloading an object."""
    client = get_s3_client()
    return client.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": bucket or settings.s3_bucket, "Key": key},
        ExpiresIn=expires_in,
        HttpMethod="GET",
    )


def public_object_url(key: str, bucket: str | None = None) -> str:
    """Build the canonical (unsigned) URL where the object lives.

    Used to persist a stable reference (e.g. ``branding.logo_url``) after
    the upload completes. The URL is the path-style MinIO/S3 address.
    """
    bucket = bucket or settings.s3_bucket
    return f"{str(settings.s3_endpoint_url).rstrip('/')}/{bucket}/{key.lstrip('/')}"
