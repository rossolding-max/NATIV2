"""Smoke: the `app` package is importable.

Replaced by the integration smoke suite (services, alembic, celery, pre-commit)
in PR 3. Exists in PR 1 only so that `pytest tests/integration/` collects at
least one test and CI does not exit 5.
"""

from __future__ import annotations

import importlib.util


def test_app_package_importable() -> None:
    spec = importlib.util.find_spec("app")
    assert spec is not None, "app package must be importable"
