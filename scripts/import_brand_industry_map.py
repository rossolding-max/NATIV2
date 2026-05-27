#!/usr/bin/env python3
"""Idempotent importer for ``data/brand_industry_map.json``.

M1 acceptance criterion: load all 290 records into the ``brand`` table;
re-export round-trips semantically identical against the source file.

Idempotency semantics per the M1 plan locked decision:
- Insert-only on first run.
- Skip-existing on re-run (log a count of skipped brands).
- NEVER upsert. M9 brand-discovery will mutate brand rows separately;
  wholesale upsert here would clobber those changes.

Usage:

    uv run python scripts/import_brand_industry_map.py
    uv run python scripts/import_brand_industry_map.py --file /path/to/custom.json
    uv run python scripts/import_brand_industry_map.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.db.session import async_session_factory
from app.models.sqla.brand import Brand
from app.repositories.brand import BrandRepository

REPO = Path(__file__).resolve().parents[1]
DEFAULT_FILE = REPO / "data" / "brand_industry_map.json"


def _slugify(name: str) -> str:
    """Derive a brand_id slug from a display name.

    Lowercase, ASCII-only, kebab-case, max 64 chars. Mirrors the regex
    enforced by ``CheckConstraint`` on ``brand.brand_id``.
    """
    import re
    import unicodedata

    normalised = unicodedata.normalize("NFKD", name)
    ascii_only = normalised.encode("ascii", "ignore").decode("ascii").lower()
    cleaned = re.sub(r"[^a-z0-9-]+", "-", ascii_only)
    cleaned = re.sub(r"^-+|-+$", "", cleaned)
    return cleaned[:64]


def _build_brand(record: dict[str, Any]) -> Brand:
    """Convert a JSON record into a Brand SQLA instance.

    Top-level scalars are surfaced as columns; everything else goes into
    the ``data`` JSONB blob.
    """
    name = record["name"]
    brand_id = _slugify(name)
    if not brand_id:
        raise ValueError(f"slugified to empty for record {name!r}")

    top_level = {
        "industry_id",
        "domain",
        "hq_country",
        "company_stage",
        "typical_campaign_tier",
    }
    payload = {k: v for k, v in record.items() if k not in top_level and k != "name"}

    return Brand(
        brand_id=brand_id,
        name=name,
        industry_id=record["industry_id"],
        domain=record.get("domain"),
        hq_country=record.get("hq_country"),
        company_stage=record.get("company_stage"),
        typical_campaign_tier=record.get("typical_campaign_tier"),
        data=payload,
    )


async def _import_async(file: Path, *, dry_run: bool) -> tuple[int, int]:
    """Returns ``(created, skipped)`` count."""
    if not file.exists():
        raise FileNotFoundError(f"Brand import source not found: {file}")
    doc = json.loads(file.read_text(encoding="utf-8"))
    brands_raw: list[dict[str, Any]] = doc["brands"]

    created = 0
    skipped = 0
    placeholder_agency = uuid4()  # brand table is global; agency_id not used by repo filter

    async with async_session_factory() as session:
        repo = BrandRepository(session, agency_id=placeholder_agency)
        for record in brands_raw:
            brand = _build_brand(record)
            if dry_run:
                exists = await repo.get_by_id(brand.brand_id)
                if exists is None:
                    created += 1
                else:
                    skipped += 1
            else:
                _, was_created = await repo.create_or_skip(brand)
                if was_created:
                    created += 1
                else:
                    skipped += 1
        if not dry_run:
            await session.commit()

    return created, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE, help="Source JSON path.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan + count only; do not commit any rows.",
    )
    args = parser.parse_args()

    created, skipped = asyncio.run(_import_async(args.file, dry_run=args.dry_run))
    if args.dry_run:
        print(f"DRY-RUN: would create {created} brand(s); would skip {skipped}.")
    else:
        print(f"Imported {created} new brand(s); skipped {skipped} existing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
