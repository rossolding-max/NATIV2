"""Smoke: the test harness runs on Python 3.12.

Kept from PR 1 — establishes the harness baseline.
"""

from __future__ import annotations

import sys


def test_python_version_is_312() -> None:
    assert sys.version_info[:2] == (3, 12), f"Expected Python 3.12, got {sys.version_info[:3]}"
