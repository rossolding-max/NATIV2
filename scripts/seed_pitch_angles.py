#!/usr/bin/env python3
"""Idempotent importer for ``data/pitch_angles.json`` (42 authored angles).

M9 ships the seeded angle library that the outreach generator picks
from. Upserts each angle by ``angle_id``; safe to re-run after edits to
the JSON file (changes propagate).

Usage:

    uv run python scripts/seed_pitch_angles.py
    uv run python scripts/seed_pitch_angles.py --file /path/to/custom.json
    uv run python scripts/seed_pitch_angles.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from app.db.session import async_session_factory
from app.models.sqla.pitch_angle import PitchAngle
from app.repositories.pitch_angle import PitchAngleRepository

REPO = Path(__file__).resolve().parents[1]
DEFAULT_FILE = REPO / "data" / "pitch_angles.json"
_AGENCY_SENTINEL = UUID(int=0)


def _build_angle(record: dict[str, Any]) -> PitchAngle:
    """Convert a JSON angle record into a PitchAngle SQLA instance."""
    return PitchAngle(
        angle_id=record["angle_id"],
        name=record["name"],
        category=record["category"],
        authored_strength_score=record["authored_strength_score"],
        data=record,
    )


async def _import_async(file: Path, *, dry_run: bool) -> tuple[int, int]:
    """Returns ``(upserted, total)`` count."""
    if not file.exists():
        raise FileNotFoundError(f"Pitch-angle source not found: {file}")
    doc = json.loads(file.read_text(encoding="utf-8"))
    angles_raw: list[dict[str, Any]] = doc["angles"]

    total = len(angles_raw)
    upserted = 0

    async with async_session_factory() as session:
        repo = PitchAngleRepository(session, agency_id=_AGENCY_SENTINEL)
        for record in angles_raw:
            new_row = _build_angle(record)
            new_row.agency_id = _AGENCY_SENTINEL
            existing = await repo.get_by_id(new_row.angle_id)
            if dry_run:
                upserted += 1
                continue
            if existing is None:
                await repo.create(new_row)
            else:
                existing.name = new_row.name
                existing.category = new_row.category
                existing.authored_strength_score = new_row.authored_strength_score
                existing.data = dict(new_row.data)
            upserted += 1
        if not dry_run:
            await session.commit()

    return upserted, total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE, help="Source JSON path.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan + count only; do not commit any rows.",
    )
    args = parser.parse_args()

    upserted, total = asyncio.run(_import_async(args.file, dry_run=args.dry_run))
    if args.dry_run:
        print(f"DRY-RUN: would upsert {upserted} of {total} angle(s).")
    else:
        print(f"Upserted {upserted} of {total} angle(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
