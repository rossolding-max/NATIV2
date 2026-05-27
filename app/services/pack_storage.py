"""Pack-artefact filesystem storage helper.

v0.1: writes pack artefacts to ``data/deals/{deal_id}/{pack_type}/v{N}/``.
Returns the file paths so the pack row in Postgres can reference them.

S3 storage deferred to M4 (which needs S3 for agency branding uploads).
M2's ``PackResult.artifacts`` carries local filesystem paths; M11+ pack
agents persist via this helper.
"""

from __future__ import annotations

from pathlib import Path

_DATA_ROOT = Path(__file__).resolve().parents[2] / "data" / "deals"


def get_pack_dir(deal_id: str, pack_type: str, version: int) -> Path:
    """Return the directory for a pack's artefacts. Creates if missing."""
    path = _DATA_ROOT / deal_id / pack_type / f"v{version}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_artefact(
    deal_id: str,
    pack_type: str,
    version: int,
    artefact_name: str,
    content: str,
) -> str:
    """Write ``content`` to ``data/deals/{deal_id}/{pack_type}/v{N}/{artefact_name}``.

    Returns the path as a string (used in ``PackResult.artifacts``).
    """
    pack_dir = get_pack_dir(deal_id, pack_type, version)
    target = pack_dir / artefact_name
    target.write_text(content, encoding="utf-8")
    return str(target)
