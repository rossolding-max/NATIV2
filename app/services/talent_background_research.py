"""Step 9 — background AI research kickoff (Celery task).

Skeletal in M5: the task fires from ``POST /api/v1/talents/{id}/activate``
once the talent reaches ``status='active'``. It writes a placeholder file
at ``data/brand_candidates/current/{talent_id}.json`` and logs the work
it WOULD do. M7 (Brand Discovery) fills in the 16-search Exa + Claude
pipeline per ``docs/brand_discovery.md``.

Fire-and-forget — the ``/activate`` endpoint must NOT block on this.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from asgiref.sync import async_to_sync

from app.celery_app import app as celery_app
from app.utils.logging import get_logger

log = get_logger(__name__)


async def _kick_off_async(talent_id: str) -> dict[str, Any]:
    """Write the brand-candidates stub + log the deferred work."""
    repo = Path(__file__).resolve().parents[2]
    out_dir = repo / "data" / "brand_candidates" / "current"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{talent_id}.json"

    now = datetime.now(UTC).isoformat()
    stub = {
        "talent_id": talent_id,
        "status": "pending_m7",
        "seeded_at": now,
        "note": (
            "M5 ships this stub. M7 (Brand Discovery) implements the "
            "16-search Exa + Claude pipeline per docs/brand_discovery.md."
        ),
    }
    out_file.write_text(json.dumps(stub, indent=2))

    log.info(
        "talent_background_research_seeded",
        talent_id=talent_id,
        stub_path=str(out_file),
    )
    return stub


@celery_app.task(name="app.services.talent_background_research.kick_off_brand_discovery")
def kick_off_brand_discovery(talent_id: str) -> dict[str, Any]:
    """Celery entry point — wraps the async stub via ``async_to_sync``.

    Following the M4 pattern: ``asyncio.run`` would close the event loop
    between back-to-back tasks on the same worker, so ``async_to_sync``
    preserves the loop.
    """
    return async_to_sync(_kick_off_async)(talent_id)
