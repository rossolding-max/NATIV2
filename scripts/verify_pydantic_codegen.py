#!/usr/bin/env python3
"""Pre-commit drift detector for schemas/ <-> app/models/pydantic/.

M0 baseline: `app/models/pydantic/` is empty/absent. Exit 0 with a notice.
M1+: compares schema manifest hash vs stored `.codegen_state.json`; fails on drift.

Idempotent. Safe to run at any milestone.
"""

from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO / "schemas"
PYDANTIC_DIR = REPO / "app" / "models" / "pydantic"
STATE_FILE = REPO / ".codegen_state.json"

# Files that are not generated even if present in PYDANTIC_DIR.
_NON_GENERATED = {"__init__.py"}


def manifest_hash() -> str:
    """SHA-256 over sorted list of (relative path, file bytes)."""
    h = sha256()
    files = sorted(SCHEMAS_DIR.rglob("*.schema.json"))
    if not files:
        raise SystemExit(
            "ERROR: no *.schema.json files found under schemas/. Verify the working directory."
        )
    for f in files:
        h.update(str(f.relative_to(REPO)).encode("utf-8"))
        h.update(b"\0")
        h.update(f.read_bytes())
    return h.hexdigest()


def has_generated_models() -> bool:
    if not PYDANTIC_DIR.exists():
        return False
    return any(p.name not in _NON_GENERATED for p in PYDANTIC_DIR.glob("*.py"))


def main() -> int:
    if not has_generated_models():
        print("M0 baseline -- no Pydantic models codegen state yet; skipping drift check.")
        return 0

    actual = manifest_hash()

    if not STATE_FILE.exists():
        print(
            "ERROR: app/models/pydantic/ is populated but .codegen_state.json is missing.\n"
            "Run `just codegen` to regenerate + record state."
        )
        return 1

    try:
        state = json.loads(STATE_FILE.read_text())
        expected = state["schema_manifest_hash"]
    except (json.JSONDecodeError, KeyError) as e:
        print(f"ERROR: .codegen_state.json malformed: {e}")
        return 1

    if actual != expected:
        print(
            f"ERROR: schemas drift detected.\n"
            f"  expected: {expected[:12]}...\n"
            f"  actual:   {actual[:12]}...\n"
            f"Run `just codegen` to regenerate."
        )
        return 1

    print("Pydantic codegen state in sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
