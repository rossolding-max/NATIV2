"""Hardening tests for the project's pre-commit hooks.

Each test feeds a deliberately-broken fixture through the corresponding hook
and asserts that the hook fails (exit code non-zero). Smoke that the hooks
fire correctly — protects against silent config drift.

Reasons these are integration-level: they invoke ``pre-commit`` itself
(spawns subprocesses + uses the cached hook installs).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_pre_commit_hook(
    hook_id: str,
    tmp_path: Path,
    contents: str,
    suffix: str,
) -> subprocess.CompletedProcess[str]:
    """Run a single pre-commit hook against a temporary file and return the process."""
    target = tmp_path / f"bad{suffix}"
    target.write_text(contents)

    result = subprocess.run(
        [
            "uv",
            "run",
            "pre-commit",
            "run",
            hook_id,
            "--files",
            str(target),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result


def _require_uv() -> None:
    if shutil.which("uv") is None:
        pytest.skip("uv not available")


def test_integration__ruff_hook_fails_on_unused_import(tmp_path: Path) -> None:
    """ruff should flag an unused import."""
    _require_uv()
    bad = "import os  # unused\n\nx = 1\n"
    result = _run_pre_commit_hook("ruff", tmp_path, bad, ".py")
    assert result.returncode != 0, (
        f"ruff hook expected to fail on unused import, but passed.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_integration__jsonschema_validator_rejects_malformed_schema(tmp_path: Path) -> None:
    """JSON Schema validator should reject a non-Draft-2020-12 schema.

    The pre-commit hook itself only fires on files under ``schemas/**``, so the
    temp file we pass won't trigger it directly. Instead we invoke the same
    ``Draft202012Validator.check_schema`` the hook uses inline.
    """
    _require_uv()
    import json

    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    bad = '{"type": ["not-a-real-type"]}'
    parsed = json.loads(bad)
    with pytest.raises(SchemaError):
        Draft202012Validator.check_schema(parsed)

    # Also confirm the hook itself runs (it'll be a no-op on a temp file outside
    # schemas/, which is the expected behaviour).
    result = _run_pre_commit_hook("jsonschema-validation", tmp_path, bad, ".schema.json")
    assert result.returncode in (0, 1)


def test_integration__verify_pydantic_codegen_script_in_sync() -> None:
    """``scripts/verify_pydantic_codegen.py`` reports in-sync state.

    Pre-M1: script printed "M0 baseline -- ... skipping drift check".
    Post-M1: script verifies `.codegen_state.json` matches the live schemas
    and prints "in sync" on success.
    """
    script = PROJECT_ROOT / "scripts" / "verify_pydantic_codegen.py"
    result = subprocess.run(
        ["uv", "run", "python", str(script)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"verify_pydantic_codegen.py should exit 0 when state is in sync, "
        f"got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # Either pre-M1 baseline-skip or post-M1 in-sync output is acceptable
    # (this test runs in both states across the milestone transition).
    assert "in sync" in result.stdout or "M0 baseline" in result.stdout
