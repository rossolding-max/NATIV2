"""Atomic persistence for a freshly-generated Discovery Prep Pack.

One transaction does it all:

1. Flip every prior version's ``is_latest=true`` to ``false`` for the deal
   (required BEFORE the new row INSERT because of the
   ``ix_prep_pack_latest_per_deal`` partial-unique index).
2. INSERT the new ``discovery_prep_pack`` row with ``is_latest=true``.
3. Write the 4 markdown artefacts + ``v{N}.json`` to the local filesystem
   via the M2 ``pack_storage`` helper.
4. Mirror the new ``prep_pack_id`` to ``deal.latest_prep_pack_id`` (scalar
   column) and ``deal.data.lead.latest_prep_pack_id`` / append to
   ``deal.data.lead.discovery_prep_pack_ids[]`` via the M11 deal repo setter.

Caller commits the session.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sqla.discovery_prep_pack import DiscoveryPrepPack
from app.repositories.deal import DealRepository
from app.repositories.discovery_prep_pack import DiscoveryPrepPackRepository
from app.services.pack_storage import write_artefact
from app.utils.logging import get_logger

log = get_logger(__name__)


_ARTEFACT_FILE_NAMES = (
    "briefing-notes.md",
    "agenda.md",
    "slides.md",
    "speaker-notes.md",
)


@dataclass
class PrepPackArtefacts:
    """Markdown bodies for the 4 v0.1 deliverables."""

    briefing_notes_md: str
    agenda_md: str
    slides_md: str
    speaker_notes_md: str


@dataclass
class PrepPackPersistResult:
    """Returned by ``persist_prep_pack`` so the caller can echo paths + ids."""

    prep_pack: DiscoveryPrepPack
    artefact_paths: dict[str, str] = field(default_factory=dict)


async def persist_prep_pack(
    session: AsyncSession,
    *,
    deal_id: str,
    agency_id: UUID,
    prep_pack_id: str,
    version: int,
    parent_version: int | None,
    pack_payload: dict[str, Any],
    artefacts: PrepPackArtefacts,
    status: str = "completed",
) -> PrepPackPersistResult:
    """Persist a freshly-generated pack atomically. Caller commits.

    ``pack_payload`` is the full JSON shape matching
    ``discovery_prep_pack.schema.json`` (the row's ``data`` blob). The
    JSONB column holds the canonical content; the markdown artefacts
    on disk are derived views the agent reads pre-call.
    """
    prep_repo = DiscoveryPrepPackRepository(session, agency_id)
    deal_repo = DealRepository(session, agency_id=agency_id)

    # Step 1: flip prior versions BEFORE the new INSERT to satisfy the
    # partial-unique index ix_prep_pack_latest_per_deal.
    flipped = await prep_repo.mark_prior_versions_not_latest(deal_id)
    log.info(
        "prep_pack_persist_flipped_prior_latest",
        deal_id=deal_id,
        flipped=flipped,
    )

    # Step 2: INSERT the new row.
    instance = DiscoveryPrepPack(
        prep_pack_id=prep_pack_id,
        deal_id=deal_id,
        version=version,
        parent_version=parent_version,
        is_latest=True,
        status=status,
        data=pack_payload,
    )
    instance.agency_id = agency_id
    await prep_repo.create(instance)

    # Step 3: write 4 markdown artefacts + v{N}.json to disk.
    bodies = (
        artefacts.briefing_notes_md,
        artefacts.agenda_md,
        artefacts.slides_md,
        artefacts.speaker_notes_md,
    )
    artefact_paths: dict[str, str] = {}
    for name, body in zip(_ARTEFACT_FILE_NAMES, bodies, strict=True):
        path = write_artefact(deal_id, "discovery_prep", version, name, body)
        artefact_paths[name] = path
    json_path = write_artefact(
        deal_id,
        "discovery_prep",
        version,
        f"v{version}.json",
        json.dumps(pack_payload, indent=2, default=str),
    )
    artefact_paths[f"v{version}.json"] = json_path

    # Step 4: mirror the new prep_pack_id onto the deal.
    await deal_repo.set_latest_prep_pack_id(deal_id, prep_pack_id)

    log.info(
        "prep_pack_persist_complete",
        deal_id=deal_id,
        prep_pack_id=prep_pack_id,
        version=version,
        artefacts=len(artefact_paths),
    )
    return PrepPackPersistResult(prep_pack=instance, artefact_paths=artefact_paths)
