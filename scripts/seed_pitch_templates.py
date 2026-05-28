#!/usr/bin/env python3
"""Idempotent importer for ``data/pitch_templates/*.json``.

M9 ships 3 default templates: buyer-direct-pitch (4 steps),
influencer-warm-intro (3 steps), champion-activation (2 steps). Each
file matches ``schemas/pitch_template.schema.json``. Upserts by
``template_id``; safe to re-run.

Usage:

    uv run python scripts/seed_pitch_templates.py
    uv run python scripts/seed_pitch_templates.py --dir /path/to/templates
    uv run python scripts/seed_pitch_templates.py --dry-run
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
from app.models.sqla.pitch_template import PitchTemplate
from app.repositories.pitch_template import PitchTemplateRepository

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DIR = REPO / "data" / "pitch_templates"
_AGENCY_SENTINEL = UUID(int=0)


def _build_template(record: dict[str, Any]) -> PitchTemplate:
    """Convert a JSON template record into a PitchTemplate SQLA instance."""
    return PitchTemplate(
        template_id=record["template_id"],
        name=record["name"],
        target_decision_role=record["target_decision_role"],
        data=record,
    )


async def _import_async(directory: Path, *, dry_run: bool) -> tuple[int, int]:
    """Returns ``(upserted, total)`` count."""
    if not directory.exists() or not directory.is_dir():
        raise FileNotFoundError(f"Templates dir not found: {directory}")
    files = sorted(directory.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"No *.json files in {directory}")

    total = len(files)
    upserted = 0

    async with async_session_factory() as session:
        repo = PitchTemplateRepository(session, agency_id=_AGENCY_SENTINEL)
        for f in files:
            record = json.loads(f.read_text(encoding="utf-8"))
            new_row = _build_template(record)
            new_row.agency_id = _AGENCY_SENTINEL
            existing = await repo.get_by_id(new_row.template_id)
            if dry_run:
                upserted += 1
                continue
            if existing is None:
                await repo.create(new_row)
            else:
                existing.name = new_row.name
                existing.target_decision_role = new_row.target_decision_role
                existing.data = dict(new_row.data)
            upserted += 1
        if not dry_run:
            await session.commit()

    return upserted, total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="Templates directory.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan + count only; do not commit any rows.",
    )
    args = parser.parse_args()

    upserted, total = asyncio.run(_import_async(args.dir, dry_run=args.dry_run))
    if args.dry_run:
        print(f"DRY-RUN: would upsert {upserted} of {total} template(s).")
    else:
        print(f"Upserted {upserted} of {total} template(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
