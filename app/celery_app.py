"""Celery client. See ``docs/architecture.md`` § 8.

v0.1 = 2 queues: ``default`` + ``llm_heavy``. v2 adds ``vendor_apis`` +
``rendering`` per V2-SCALE-01.

Beat schedule populated per-milestone. M4 adds the agency-warmup poll
(``app.services.agency_warmup.poll_mailbox_warmup_status``) at the
hourly cadence borrowed from ``cron_phase_4_8_detection_other_seconds``.
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
        include=[
            "app.tasks.echo",
            "app.tasks.pack_generation",
            "app.services.agency_warmup",
            "app.services.talent_background_research",
        ],
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
        # ── Beat (populated per milestone) ────────────────────────────
        beat_schedule={
            "agency-warmup-poll": {
                "task": "app.services.agency_warmup.poll_mailbox_warmup_status",
                # M4: hourly cadence reuses the Phase-4.8 "other" cron until
                # a dedicated warmup interval is added.
                "schedule": float(settings.cron_phase_4_8_detection_other_seconds),
                "options": {"queue": "default"},
            },
        },
    )

    return celery_app


app: Celery = _build_app()
