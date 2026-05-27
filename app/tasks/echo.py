"""Celery echo task. Smoke-test only.

Used by ``tests/integration/test_smoke_celery.py`` to verify the broker +
worker + result backend round-trip on both queues (``default`` + ``llm_heavy``).
Remove or refactor when the first real task ships.
"""

from __future__ import annotations

from app.celery_app import app


@app.task(name="app.tasks.echo.echo_task")
def echo_task(message: str) -> str:
    """Return the input verbatim. Smoke test for broker + worker."""
    return message
