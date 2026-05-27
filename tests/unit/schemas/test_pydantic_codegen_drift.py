"""Hardening tests for ``scripts/verify_pydantic_codegen.py``.

Verifies the drift detector:
- Exits 0 when the recorded manifest hash matches the live schema state.
- Exits 1 when any schema file is mutated (and reverts cleanly).
- The recorded ``.codegen_state.json`` is consistent with the schema corpus.

Runs against the actual ``schemas/`` directory + the actual generated
``app/models/pydantic/`` tree. Does NOT regenerate the models (that's
expensive); only checks state-file consistency.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = PROJECT_ROOT / "scripts" / "verify_pydantic_codegen.py"
STATE_FILE = PROJECT_ROOT / ".codegen_state.json"
SCHEMAS_DIR = PROJECT_ROOT / "schemas"


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_unit__drift_detector_in_sync_at_baseline() -> None:
    """The committed `.codegen_state.json` matches the committed schemas."""
    if not STATE_FILE.exists():
        # PR 1 ships .codegen_state.json; if it's missing in a future revert
        # state, this test is a clear signal.
        msg = (
            "Expected `.codegen_state.json` to exist post-M1; run `just codegen` "
            "to regenerate it after pulling fresh schemas."
        )
        raise AssertionError(msg)
    result = _run_script()
    assert result.returncode == 0, (
        f"Drift detector flagged a mismatch at baseline.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "in sync" in result.stdout


def test_unit__drift_detector_recorded_state_is_well_formed() -> None:
    """`.codegen_state.json` carries a sha256 manifest hash key."""
    state = json.loads(STATE_FILE.read_text())
    assert "schema_manifest_hash" in state
    h = state["schema_manifest_hash"]
    assert isinstance(h, str)
    assert len(h) == 64  # sha256 hex digest length
    assert all(c in "0123456789abcdef" for c in h)


def test_unit__drift_detector_fails_when_schema_mutated(tmp_path: Path) -> None:
    """Edit a schema file in a copied repo subset; drift detector fails."""
    # Build a minimal isolated copy: state file + schemas/ + the script.
    work = tmp_path / "repo"
    (work / "schemas").mkdir(parents=True)
    (work / "scripts").mkdir(parents=True)
    (work / "app" / "models" / "pydantic").mkdir(parents=True)

    # Copy schemas verbatim (including _shared subdir).
    for src in SCHEMAS_DIR.rglob("*.schema.json"):
        rel = src.relative_to(SCHEMAS_DIR)
        dest = work / "schemas" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dest)

    # Copy state file + script.
    shutil.copy(STATE_FILE, work / ".codegen_state.json")
    shutil.copy(SCRIPT, work / "scripts" / SCRIPT.name)

    # Make `has_generated_models` return True without copying the entire
    # generated tree: a single placeholder .py file is enough.
    (work / "app" / "models" / "pydantic" / "placeholder.py").write_text(
        "# generated placeholder\n"
    )

    # Mutate one schema (append harmless whitespace).
    target = next((work / "schemas").glob("*.schema.json"))
    target.write_text(target.read_text() + "\n  /* synthetic drift */\n")

    # Run drift check in the isolated copy.
    result = subprocess.run(
        [sys.executable, str(work / "scripts" / SCRIPT.name)],
        cwd=work,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, "Drift detector should fail on schema mutation"
    assert "drift detected" in result.stdout


def test_unit__drift_detector_record_writes_state(tmp_path: Path) -> None:
    """`--record` flag writes a fresh hash to `.codegen_state.json`."""
    work = tmp_path / "repo"
    (work / "schemas").mkdir(parents=True)
    (work / "scripts").mkdir(parents=True)
    (work / "app" / "models" / "pydantic").mkdir(parents=True)

    for src in SCHEMAS_DIR.rglob("*.schema.json"):
        rel = src.relative_to(SCHEMAS_DIR)
        dest = work / "schemas" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dest)
    shutil.copy(SCRIPT, work / "scripts" / SCRIPT.name)

    result = subprocess.run(
        [sys.executable, str(work / "scripts" / SCRIPT.name), "--record"],
        cwd=work,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    written = json.loads((work / ".codegen_state.json").read_text())
    assert "schema_manifest_hash" in written
    assert len(written["schema_manifest_hash"]) == 64
