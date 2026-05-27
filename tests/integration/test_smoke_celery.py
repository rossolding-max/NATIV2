"""Smoke: the Celery client + ``echo_task`` work on both queues.

Proves the v0.1 two-queue topology (``default`` + ``llm_heavy``) is correctly
registered. Runs in-process via Celery's "eager" mode to avoid spinning up a
worker; the broker connectivity smoke is covered by ``test_smoke_services``.
"""

from __future__ import annotations

import pytest


def test_integration__celery_two_queues_registered() -> None:
    """Verify the queue topology matches the v0.1 spec."""
    from app.celery_app import app as celery_app

    queues = celery_app.conf.task_queues
    queue_names = {q.name for q in queues}
    assert queue_names == {"default", "llm_heavy"}


def test_integration__celery_default_queue_is_default() -> None:
    """Tasks dispatched without an explicit queue land on `default`."""
    from app.celery_app import app as celery_app

    assert celery_app.conf.task_default_queue == "default"


def test_integration__celery_beat_schedule_empty_at_m0() -> None:
    """No Beat tasks land in M0 — per-milestone additions arrive M7+."""
    from app.celery_app import app as celery_app

    assert celery_app.conf.beat_schedule == {}


@pytest.mark.parametrize("queue", ["default", "llm_heavy"])
def test_integration__echo_task_round_trips_eager(queue: str) -> None:
    """In eager mode, ``echo_task`` returns the message verbatim on both queues."""
    from app.celery_app import app as celery_app
    from app.tasks.echo import echo_task

    celery_app.conf.task_always_eager = True
    try:
        result = echo_task.apply(args=("hello",), queue=queue)  # type: ignore[attr-defined]
        assert result.get(timeout=2) == "hello"
    finally:
        celery_app.conf.task_always_eager = False


def test_integration__celery_utc_only() -> None:
    """UTC discipline enforced at the Celery layer (per CLAUDE.md strict don'ts)."""
    from app.celery_app import app as celery_app

    assert celery_app.conf.enable_utc is True
    assert celery_app.conf.timezone == "UTC"
