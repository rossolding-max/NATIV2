"""Hardening tests for ``app.api.responses``.

Covers envelope shape, auto-populated meta, and pagination math.
"""

from __future__ import annotations

from app.api.responses import APIError, APIResponse, make_meta


def test_unit__make_meta_populates_request_id_and_timestamp() -> None:
    meta = make_meta()
    assert meta.request_id.startswith("req_")
    assert meta.api_version == "v1"
    # Timestamp is UTC.
    assert meta.timestamp.utcoffset() is not None
    assert meta.timestamp.utcoffset().total_seconds() == 0  # type: ignore[union-attr]


def test_unit__make_meta_pagination_math() -> None:
    meta = make_meta(page=2, page_size=10, total_count=23)
    assert meta.page == 2
    assert meta.page_size == 10
    assert meta.total_count == 23
    assert meta.total_pages == 3  # ceil(23 / 10)


def test_unit__make_meta_pagination_exact_division() -> None:
    meta = make_meta(page=1, page_size=10, total_count=20)
    assert meta.total_pages == 2


def test_unit__make_meta_pagination_total_zero() -> None:
    meta = make_meta(page=1, page_size=10, total_count=0)
    assert meta.total_pages == 0


def test_unit__make_meta_pagination_absent_by_default() -> None:
    meta = make_meta()
    assert meta.page is None
    assert meta.page_size is None
    assert meta.total_count is None
    assert meta.total_pages is None


def test_unit__api_response_envelope_shape() -> None:
    body = APIResponse[dict[str, str]](
        data={"hello": "world"},
        meta=make_meta(),
        errors=[],
    )
    dumped = body.model_dump(mode="json")
    assert set(dumped.keys()) == {"data", "meta", "errors"}
    assert dumped["data"] == {"hello": "world"}
    assert dumped["errors"] == []


def test_unit__api_response_with_errors() -> None:
    body = APIResponse[None](
        data=None,
        meta=make_meta(),
        errors=[APIError(code="VALIDATION_ERROR", message="bad input", field="email")],
    )
    dumped = body.model_dump(mode="json")
    assert dumped["data"] is None
    assert dumped["errors"][0]["code"] == "VALIDATION_ERROR"
    assert dumped["errors"][0]["field"] == "email"
