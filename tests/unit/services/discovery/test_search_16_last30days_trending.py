"""Search 16 (last30days trending brand mentions)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from app.services.discovery import search_16_last30days_trending


def _brand_map(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"brands": list(entries)}


def _report(
    reddit_items: list[dict[str, Any]] | None = None, x_items: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "topic": "test",
        "range_from": "2026-04-28",
        "range_to": "2026-05-28",
        "generated_at": "2026-05-28",
        "mode": "both",
        "reddit": reddit_items or [],
        "x": x_items or [],
    }


@pytest.mark.asyncio
async def test_unit__search_16__no_industries_returns_empty(tmp_path: Path) -> None:
    sources = await search_16_last30days_trending.run(
        top_industry_ids=[],
        brand_industry_map=_brand_map({"name": "Nike", "industry_id": "sportswear"}),
        skill_path=tmp_path / "nope.py",
    )
    assert sources == []


@pytest.mark.asyncio
async def test_unit__search_16__missing_skill_path_returns_empty(tmp_path: Path) -> None:
    sources = await search_16_last30days_trending.run(
        top_industry_ids=["sportswear"],
        brand_industry_map=_brand_map({"name": "Nike", "industry_id": "sportswear"}),
        skill_path=tmp_path / "does_not_exist.py",
    )
    assert sources == []


@pytest.mark.asyncio
async def test_unit__search_16__brand_mention_in_reddit_title_emits_source(
    tmp_path: Path,
) -> None:
    """When the skill output mentions 'Nike' in a Reddit title, Search 16
    surfaces a CandidateSource for Nike."""
    skill_path = tmp_path / "last30days.py"
    skill_path.write_text("# stub")
    bim = _brand_map(
        {"name": "Nike", "industry_id": "sportswear"},
        {"name": "Adidas", "industry_id": "sportswear"},
    )
    report = _report(
        reddit_items=[{"title": "Just bought a pair of Nike running shoes", "why_relevant": "x"}]
    )

    async def _fake_invoke(*, topic: str, **_: Any) -> dict[str, Any]:
        return report

    with patch.object(search_16_last30days_trending, "_invoke_skill", new=_fake_invoke):
        sources = await search_16_last30days_trending.run(
            top_industry_ids=["sportswear"],
            brand_industry_map=bim,
            skill_path=skill_path,
        )
    assert len(sources) == 1
    assert sources[0].brand_id == "nike"
    assert sources[0].search_tag == "last30days_trending"
    assert sources[0].weight == 0.06


@pytest.mark.asyncio
async def test_unit__search_16__substring_match_avoids_false_positives(
    tmp_path: Path,
) -> None:
    """'AG' (a brand alias) must not match 'stage' or 'page'."""
    skill_path = tmp_path / "last30days.py"
    skill_path.write_text("# stub")
    bim = _brand_map(
        {"name": "Athletic Greens", "industry_id": "supplements-brands", "aliases": ["AG"]},
    )
    report = _report(
        reddit_items=[{"title": "Onstage performance from page 3", "why_relevant": "x"}]
    )

    async def _fake_invoke(*, topic: str, **_: Any) -> dict[str, Any]:
        return report

    with patch.object(search_16_last30days_trending, "_invoke_skill", new=_fake_invoke):
        sources = await search_16_last30days_trending.run(
            top_industry_ids=["supplements-brands"],
            brand_industry_map=bim,
            skill_path=skill_path,
        )
    assert sources == []


@pytest.mark.asyncio
async def test_unit__search_16__matches_via_alias(tmp_path: Path) -> None:
    skill_path = tmp_path / "last30days.py"
    skill_path.write_text("# stub")
    bim = _brand_map(
        {"name": "Athletic Greens", "industry_id": "supplements-brands", "aliases": ["AG1"]},
    )
    report = _report(x_items=[{"text": "Drinking my AG1 every morning"}])

    async def _fake_invoke(*, topic: str, **_: Any) -> dict[str, Any]:
        return report

    with patch.object(search_16_last30days_trending, "_invoke_skill", new=_fake_invoke):
        sources = await search_16_last30days_trending.run(
            top_industry_ids=["supplements-brands"],
            brand_industry_map=bim,
            skill_path=skill_path,
        )
    assert len(sources) == 1
    assert sources[0].brand_id == "athletic-greens"


@pytest.mark.asyncio
async def test_unit__search_16__dedupes_across_industries(tmp_path: Path) -> None:
    """Same brand mentioned in two industries' reports -> one source."""
    skill_path = tmp_path / "last30days.py"
    skill_path.write_text("# stub")
    bim = _brand_map({"name": "Nike", "industry_id": "sportswear"})

    async def _fake_invoke(*, topic: str, **_: Any) -> dict[str, Any]:
        return _report(reddit_items=[{"title": "Nike is everywhere", "why_relevant": "x"}])

    with patch.object(search_16_last30days_trending, "_invoke_skill", new=_fake_invoke):
        sources = await search_16_last30days_trending.run(
            top_industry_ids=["sportswear", "activewear"],
            brand_industry_map=bim,
            skill_path=skill_path,
        )
    assert len(sources) == 1


@pytest.mark.asyncio
async def test_unit__search_16__industry_cap_respected(tmp_path: Path) -> None:
    """If 5 industries passed but max_industries=2, only 2 invocations happen."""
    skill_path = tmp_path / "last30days.py"
    skill_path.write_text("# stub")
    bim = _brand_map({"name": "X", "industry_id": "x"})

    call_count = {"n": 0}

    async def _fake_invoke(*, topic: str, **_: Any) -> dict[str, Any]:
        call_count["n"] += 1
        return _report()

    with patch.object(search_16_last30days_trending, "_invoke_skill", new=_fake_invoke):
        await search_16_last30days_trending.run(
            top_industry_ids=["a", "b", "c", "d", "e"],
            brand_industry_map=bim,
            skill_path=skill_path,
            max_industries=2,
        )
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_unit__search_16__subprocess_invocation_uses_correct_args(
    tmp_path: Path,
) -> None:
    """Verify the subprocess is called with the expected CLI shape."""
    skill_path = tmp_path / "last30days.py"
    skill_path.write_text("# stub")

    captured: dict[str, Any] = {}

    class _FakeProc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return json.dumps(_report()).encode(), b""

    async def _fake_create_subprocess_exec(*args: Any, **_kwargs: Any) -> _FakeProc:
        captured["args"] = args
        return _FakeProc()

    with patch("asyncio.create_subprocess_exec", new=_fake_create_subprocess_exec):
        result = await search_16_last30days_trending._invoke_skill(  # pyright: ignore[reportPrivateUsage]
            topic="activewear trending brands",
            skill_path=skill_path,
            mock=False,
            timeout_s=10.0,
        )
    assert result is not None
    assert "--emit=json" in captured["args"]
    assert "--quick" in captured["args"]
    assert "activewear trending brands" in captured["args"]
    assert "--mock" not in captured["args"]


@pytest.mark.asyncio
async def test_unit__search_16__mock_mode_passes_mock_flag(tmp_path: Path) -> None:
    skill_path = tmp_path / "last30days.py"
    skill_path.write_text("# stub")
    captured: dict[str, Any] = {}

    class _FakeProc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return json.dumps(_report()).encode(), b""

    async def _fake_create_subprocess_exec(*args: Any, **_kwargs: Any) -> _FakeProc:
        captured["args"] = args
        return _FakeProc()

    with patch("asyncio.create_subprocess_exec", new=_fake_create_subprocess_exec):
        await search_16_last30days_trending._invoke_skill(  # pyright: ignore[reportPrivateUsage]
            topic="x", skill_path=skill_path, mock=True, timeout_s=10.0
        )
    assert "--mock" in captured["args"]


@pytest.mark.asyncio
async def test_unit__search_16__subprocess_nonzero_returns_none(tmp_path: Path) -> None:
    skill_path = tmp_path / "last30days.py"
    skill_path.write_text("# stub")

    class _FakeProc:
        returncode = 1

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b"error"

    async def _fake_create_subprocess_exec(*args: Any, **_kwargs: Any) -> _FakeProc:
        return _FakeProc()

    with patch("asyncio.create_subprocess_exec", new=_fake_create_subprocess_exec):
        result = await search_16_last30days_trending._invoke_skill(  # pyright: ignore[reportPrivateUsage]
            topic="x", skill_path=skill_path, mock=False, timeout_s=10.0
        )
    assert result is None
