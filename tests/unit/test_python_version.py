"""Smoke: the test harness runs on Python 3.12.

Replaced by the full hardening suite in PR 3; exists in PR 1 only so that
`pytest tests/unit/` collects at least one test and CI does not exit 5.
"""

from __future__ import annotations

import sys


def test_python_version_is_312() -> None:
    assert sys.version_info[:2] == (3, 12), f"Expected Python 3.12, got {sys.version_info[:3]}"
