"""``persist_prep_pack`` — flip-then-insert, 5 artefacts, deal mirror update."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.services import prep_pack_persistence
from app.services.prep_pack_persistence import PrepPackArtefacts, persist_prep_pack

_AGENCY_ID = UUID(int=0)


def _patch_pack_storage_to_tmpdir(tmpdir: Path):
    """Reroute write_artefact's _DATA_ROOT into a tmpdir for the duration of a test."""
    return patch.object(prep_pack_persistence, "write_artefact", side_effect=_fake_write(tmpdir))


def _fake_write(tmpdir: Path):
    def _impl(deal_id: str, pack_type: str, version: int, name: str, body: str) -> str:
        d = tmpdir / deal_id / pack_type / f"v{version}"
        d.mkdir(parents=True, exist_ok=True)
        path = d / name
        path.write_text(body, encoding="utf-8")
        return str(path)

    return _impl


def _artefacts() -> PrepPackArtefacts:
    return PrepPackArtefacts(
        briefing_notes_md="# briefing",
        agenda_md="# agenda",
        slides_md="# slides",
        speaker_notes_md="# speaker notes",
    )


@pytest.mark.asyncio
async def test_unit__persist__flip_prior_then_insert_order() -> None:
    """``mark_prior_versions_not_latest`` MUST be called BEFORE ``create``."""
    session = MagicMock()
    call_order: list[str] = []

    prep_repo = MagicMock()
    prep_repo.mark_prior_versions_not_latest = AsyncMock(
        side_effect=lambda *_a, **_k: call_order.append("flip") or 0
    )
    prep_repo.create = AsyncMock(
        side_effect=lambda inst: call_order.append("insert") or inst
    )

    deal_repo = MagicMock()
    deal_repo.set_latest_prep_pack_id = AsyncMock()

    with (
        tempfile.TemporaryDirectory() as td,
        _patch_pack_storage_to_tmpdir(Path(td)),
        patch.object(
            prep_pack_persistence, "DiscoveryPrepPackRepository", return_value=prep_repo
        ),
        patch.object(prep_pack_persistence, "DealRepository", return_value=deal_repo),
    ):
        await persist_prep_pack(
            session,
            deal_id="deal_pipeline_x",
            agency_id=_AGENCY_ID,
            prep_pack_id="prep_x_v1",
            version=1,
            parent_version=None,
            pack_payload={"prep_pack_id": "prep_x_v1", "version": 1},
            artefacts=_artefacts(),
        )

    assert call_order == ["flip", "insert"]
    deal_repo.set_latest_prep_pack_id.assert_awaited_once_with(
        "deal_pipeline_x", "prep_x_v1"
    )


@pytest.mark.asyncio
async def test_unit__persist__writes_5_artefacts_with_expected_names() -> None:
    session = MagicMock()
    prep_repo = MagicMock()
    prep_repo.mark_prior_versions_not_latest = AsyncMock(return_value=0)
    prep_repo.create = AsyncMock(side_effect=lambda inst: inst)

    deal_repo = MagicMock()
    deal_repo.set_latest_prep_pack_id = AsyncMock()

    with (
        tempfile.TemporaryDirectory() as td,
        _patch_pack_storage_to_tmpdir(Path(td)),
        patch.object(
            prep_pack_persistence, "DiscoveryPrepPackRepository", return_value=prep_repo
        ),
        patch.object(prep_pack_persistence, "DealRepository", return_value=deal_repo),
    ):
        out = await persist_prep_pack(
            session,
            deal_id="deal_pipeline_y",
            agency_id=_AGENCY_ID,
            prep_pack_id="prep_y_v2",
            version=2,
            parent_version=1,
            pack_payload={"prep_pack_id": "prep_y_v2", "version": 2},
            artefacts=_artefacts(),
        )

        names = set(out.artefact_paths.keys())
        assert names == {
            "briefing-notes.md",
            "agenda.md",
            "slides.md",
            "speaker-notes.md",
            "v2.json",
        }
        # The v{N}.json content is the pack payload JSON-serialised.
        json_path = Path(out.artefact_paths["v2.json"])
        assert json_path.exists()
        loaded = json.loads(json_path.read_text())
        assert loaded == {"prep_pack_id": "prep_y_v2", "version": 2}


@pytest.mark.asyncio
async def test_unit__persist__creates_row_with_is_latest_true_and_status() -> None:
    """The inserted row must have ``is_latest=True`` + the requested status."""
    session = MagicMock()
    prep_repo = MagicMock()
    prep_repo.mark_prior_versions_not_latest = AsyncMock(return_value=0)
    captured: list = []

    async def _capture(instance):
        captured.append(instance)
        return instance

    prep_repo.create = AsyncMock(side_effect=_capture)

    deal_repo = MagicMock()
    deal_repo.set_latest_prep_pack_id = AsyncMock()

    with (
        tempfile.TemporaryDirectory() as td,
        _patch_pack_storage_to_tmpdir(Path(td)),
        patch.object(
            prep_pack_persistence, "DiscoveryPrepPackRepository", return_value=prep_repo
        ),
        patch.object(prep_pack_persistence, "DealRepository", return_value=deal_repo),
    ):
        await persist_prep_pack(
            session,
            deal_id="deal_pipeline_z",
            agency_id=_AGENCY_ID,
            prep_pack_id="prep_z_v1",
            version=1,
            parent_version=None,
            pack_payload={"prep_pack_id": "prep_z_v1", "version": 1},
            artefacts=_artefacts(),
            status="completed",
        )

    assert len(captured) == 1
    row = captured[0]
    assert row.is_latest is True
    assert row.status == "completed"
    assert row.version == 1
    assert row.parent_version is None
    assert row.prep_pack_id == "prep_z_v1"


@pytest.mark.asyncio
async def test_unit__persist__regen_carries_parent_version_through() -> None:
    """v2 regen records parent_version=1 + writes v2.json."""
    session = MagicMock()
    prep_repo = MagicMock()
    prep_repo.mark_prior_versions_not_latest = AsyncMock(return_value=1)
    captured: list = []
    prep_repo.create = AsyncMock(side_effect=lambda inst: captured.append(inst) or inst)

    deal_repo = MagicMock()
    deal_repo.set_latest_prep_pack_id = AsyncMock()

    with (
        tempfile.TemporaryDirectory() as td,
        _patch_pack_storage_to_tmpdir(Path(td)),
        patch.object(
            prep_pack_persistence, "DiscoveryPrepPackRepository", return_value=prep_repo
        ),
        patch.object(prep_pack_persistence, "DealRepository", return_value=deal_repo),
    ):
        out = await persist_prep_pack(
            session,
            deal_id="deal_pipeline_q",
            agency_id=_AGENCY_ID,
            prep_pack_id="prep_q_v2",
            version=2,
            parent_version=1,
            pack_payload={"prep_pack_id": "prep_q_v2", "version": 2, "parent_version": 1},
            artefacts=_artefacts(),
        )

    assert captured[0].parent_version == 1
    assert captured[0].version == 2
    assert "v2.json" in out.artefact_paths
