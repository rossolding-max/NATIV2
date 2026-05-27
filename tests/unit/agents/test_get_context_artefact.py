"""Unit tests for ``app.agents.tools.get_context_artefact``.

Covers the standalone parsing functions + the dispatch in
``get_context_artefact``. S3 fetch is exercised in the integration suite
against MinIO; this module uses ``raw_bytes`` injection so no Docker is
needed.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import docx
import pytest
from pypdf import PdfWriter

from app.agents.tools import get_context_artefact as gca
from app.agents.tools.get_context_artefact import (
    ContextArtefact,
    InlineImage,
    get_context_artefact,
    image_to_inline,
    parse_docx_bytes,
    parse_pdf_bytes,
)
from app.errors import BusinessRuleError, ValidationError


def _sniff_mime(filename: str | None, content_type: str | None) -> str:
    """Public-test wrapper around the private helper to satisfy pyright."""
    return gca._sniff_mime(filename, content_type)  # pyright: ignore[reportPrivateUsage]


def _make_blank_pdf(num_pages: int = 1) -> bytes:
    """Build a minimal valid PDF in memory (no text content)."""
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _make_docx_with_paragraphs(paragraphs: list[str]) -> bytes:
    """Build a DOCX in memory containing the given paragraph texts."""
    document = docx.Document()
    for text in paragraphs:
        document.add_paragraph(text)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


@pytest.mark.parametrize(
    ("filename", "content_type", "expected"),
    [
        ("media-pack.pdf", None, "application/pdf"),
        (
            "brief.DOCX",
            None,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        ("avatar.png", None, "image/png"),
        ("avatar.JPG", None, "image/jpeg"),
        (None, "image/png", "image/png"),
        (None, None, "application/octet-stream"),
    ],
)
def test_unit__sniff_mime(filename: str | None, content_type: str | None, expected: str) -> None:
    assert _sniff_mime(filename, content_type) == expected


def test_unit__parse_pdf_bytes__page_count() -> None:
    pdf = _make_blank_pdf(num_pages=3)
    text, page_count = parse_pdf_bytes(pdf)
    assert page_count == 3
    # Blank pages → empty extracted text.
    assert text == ""


def test_unit__parse_docx_bytes__paragraphs_concatenated() -> None:
    docx_bytes = _make_docx_with_paragraphs(["First line", "Second line", "", "Third"])
    text = parse_docx_bytes(docx_bytes)
    assert "First line" in text
    assert "Second line" in text
    assert "Third" in text


def test_unit__image_to_inline__png_roundtrip() -> None:
    # 1x1 transparent PNG header.
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    inline = image_to_inline(png_bytes, "image/png")
    assert isinstance(inline, InlineImage)
    assert inline.media_type == "image/png"
    assert inline.size_bytes == len(png_bytes)
    assert base64.standard_b64decode(inline.data_b64) == png_bytes


def test_unit__image_to_inline__rejects_gif() -> None:
    with pytest.raises(ValidationError):
        image_to_inline(b"GIF89a", "image/gif")


def test_unit__image_to_inline__rejects_oversize() -> None:
    big = b"\x00" * (6 * 1024 * 1024)
    with pytest.raises(ValidationError, match="MB per-image"):
        image_to_inline(big, "image/png")


async def test_unit__get_context_artefact__requires_exactly_one_source() -> None:
    with pytest.raises(BusinessRuleError):
        await get_context_artefact("a1")  # neither s3_key nor raw_bytes

    with pytest.raises(BusinessRuleError):
        await get_context_artefact("a1", s3_key="x", raw_bytes=b"y")  # both


async def test_unit__get_context_artefact__pdf_path() -> None:
    pdf = _make_blank_pdf(num_pages=2)
    artefact = await get_context_artefact("media-pack-1", raw_bytes=pdf, filename="media-pack.pdf")
    assert isinstance(artefact, ContextArtefact)
    assert artefact.kind == "pdf"
    assert artefact.metadata["page_count"] == 2
    assert artefact.metadata["mime"] == "application/pdf"


async def test_unit__get_context_artefact__docx_path() -> None:
    docx_bytes = _make_docx_with_paragraphs(["Talent bio paragraph.", "Brand work line."])
    artefact = await get_context_artefact("brief-1", raw_bytes=docx_bytes, filename="brief.docx")
    assert artefact.kind == "docx"
    assert "Talent bio paragraph." in artefact.text
    assert "Brand work line." in artefact.text


async def test_unit__get_context_artefact__unknown_mime_returns_unknown_kind() -> None:
    artefact = await get_context_artefact(
        "weird-1", raw_bytes=b"unknown content", filename="thing.xyz"
    )
    assert artefact.kind == "unknown"
    assert artefact.text == ""


def test_unit__resolve_fixture_paths_exist() -> None:
    """Sanity-check that the M0 fixtures dir exists so the integration suite
    can drop sample PDFs there later if needed."""
    repo = Path(__file__).resolve().parents[3]
    assert (repo / "tests" / "fixtures").is_dir()
