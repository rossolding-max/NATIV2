"""Celery client. See ``docs/architecture.md`` § 8.

v0.1 = 2 queues: ``default`` + ``llm_heavy``. v2 adds ``vendor_apis`` +
``rendering`` per V2-SCALE-01.

The Beat schedule is empty at M0 — per-milestone cron tasks land in M7+
(discovery cron), M11+ (pack auto-fire), M14+ (detection polling), M16
(auto-archive check), and so on.
"""

from __future__ import annotations

from celery import Celery
from kombu import Queue

from app.config import settings


def _build_app() -> Celery:
    celery_app = Celery(
        "nativ2",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=["app.tasks.echo"],
    )

    celery_app.conf.update(
        # ── Time + UTC discipline ─────────────────────────────────────
        enable_utc=True,
        timezone="UTC",
        # ── Queues (v0.1 = 2) ─────────────────────────────────────────
        task_default_queue="default",
        task_queues=(
            Queue("default"),
            Queue("llm_heavy"),
        ),
        # ── Lifecycle + reliability ───────────────────────────────────
        task_track_started=settings.celery_task_track_started,
        task_time_limit=settings.celery_task_time_limit_seconds,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        # ── Beat (empty at M0; populated per milestone) ───────────────
        beat_schedule={},
    )

    return celery_app


app: Celery = _build_app()
