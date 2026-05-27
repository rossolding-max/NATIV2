"""Branding asset upload helpers (Phase 0 Step 1.5).

The REST endpoint exposes a presigned PUT URL for the agency to upload
their logo to S3/MinIO. After the upload succeeds, the agency PATCHes
``branding.logo_url`` with the resulting public URL.

S3 key format: ``agency/{agency_uuid}/branding/{logo_filename}``. The
filename keeps the user's extension so the renderer can pick the right
MIME type later.
"""

from __future__ import annotations

from uuid import UUID

from app.config import settings
from app.errors import ValidationError
from app.utils.s3 import (
    generate_presigned_put_url,
    public_object_url,
)

_ALLOWED_LOGO_CONTENT_TYPES: frozenset[str] = frozenset(
    {"image/png", "image/jpeg", "image/svg+xml"}
)
_EXTENSION_BY_CONTENT_TYPE: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/svg+xml": "svg",
}


def _max_logo_size_bytes() -> int:
    return settings.upload_max_file_size_mb * 1024 * 1024


def validate_logo_metadata(*, content_type: str, declared_size_bytes: int | None = None) -> None:
    """Reject MIME / size combinations we don't want stored.

    ``declared_size_bytes`` is optional — the client sends what they
    intend to upload, so we can fail early instead of letting MinIO
    accept a huge PUT.
    """
    if content_type not in _ALLOWED_LOGO_CONTENT_TYPES:
        raise ValidationError(
            f"logo content_type must be one of {sorted(_ALLOWED_LOGO_CONTENT_TYPES)}",
            field="content_type",
            detail={"received": content_type},
        )
    if declared_size_bytes is not None:
        limit = _max_logo_size_bytes()
        if declared_size_bytes <= 0:
            raise ValidationError(
                "logo declared size must be positive",
                field="size_bytes",
                detail={"received": declared_size_bytes},
            )
        if declared_size_bytes > limit:
            raise ValidationError(
                f"logo exceeds maximum size of {settings.upload_max_file_size_mb} MB",
                field="size_bytes",
                detail={"received": declared_size_bytes, "limit_bytes": limit},
            )


def _logo_key(agency_id: UUID, content_type: str) -> str:
    extension = _EXTENSION_BY_CONTENT_TYPE[content_type]
    return f"agency/{agency_id}/branding/logo.{extension}"


def generate_presigned_logo_put_url(
    *, agency_id: UUID, content_type: str, declared_size_bytes: int | None = None
) -> dict[str, str]:
    """Return a single-use upload URL + the canonical public URL to persist.

    Caller (REST handler) returns both fields to the client. The client
    uploads to ``upload_url`` with ``Content-Type: {content_type}`` then
    PATCHes ``branding.logo_url = public_url``.
    """
    validate_logo_metadata(content_type=content_type, declared_size_bytes=declared_size_bytes)
    key = _logo_key(agency_id, content_type)
    upload_url = generate_presigned_put_url(
        key=key,
        content_type=content_type,
        expires_in=settings.upload_presign_ttl_seconds,
    )
    return {
        "upload_url": upload_url,
        "public_url": public_object_url(key),
        "key": key,
        "content_type": content_type,
        "expires_in_seconds": str(settings.upload_presign_ttl_seconds),
    }
