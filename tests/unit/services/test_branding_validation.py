"""Unit tests for ``app.services.branding.validate_logo_metadata``."""

from __future__ import annotations

import pytest

from app.errors import ValidationError
from app.services.branding import validate_logo_metadata


@pytest.mark.parametrize("content_type", ["image/png", "image/jpeg", "image/svg+xml"])
def test_unit__allowed_content_types(content_type: str) -> None:
    validate_logo_metadata(content_type=content_type, declared_size_bytes=1024)


@pytest.mark.parametrize("content_type", ["image/gif", "application/pdf", "text/plain"])
def test_unit__rejected_content_types(content_type: str) -> None:
    with pytest.raises(ValidationError):
        validate_logo_metadata(content_type=content_type)


def test_unit__zero_size__rejected() -> None:
    with pytest.raises(ValidationError, match="positive"):
        validate_logo_metadata(content_type="image/png", declared_size_bytes=0)


def test_unit__oversize__rejected() -> None:
    # 200 MB > default 100 MB upload limit.
    with pytest.raises(ValidationError, match="maximum"):
        validate_logo_metadata(content_type="image/png", declared_size_bytes=200 * 1024 * 1024)


def test_unit__size_unknown__not_rejected() -> None:
    validate_logo_metadata(content_type="image/png", declared_size_bytes=None)
