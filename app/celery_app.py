"""Celery client. See ``docs/architecture.md`` § 8.

v0.1 = 2 queues: ``default`` + ``llm_heavy``. v2 adds ``vendor_apis`` +
``rendering`` per V2-SCALE-01.

Beat schedule populated per-milestone. M4 adds the agency-warmup poll
(``app.services.agency_warmup.poll_mailbox_warmup_status``) at the
hourly cadence borrowed from ``cron_phase_4_8_detection_other_seconds``.
"""

from __future__ import annotations

from typing import Any

from celery import Celery
from celery.signals import worker_process_init
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
            "app.services.contact_enrichment_task",
            "app.services.contact_email_reveal_task",
            "app.services.outreach_generation_task",
            "app.services.enrollment_state_sync",
            "app.services.deal_phase_4_5_auto_fire_task",
            "app.services.deal_auto_archive_task",
            "app.services.discovery_phase_4_monthly",
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
            "enrollment-state-sync": {
                # M9: reconcile active enrollments with Smartlead every 5 min
                # to catch any webhook misses (network failures, dedupe bugs).
                "task": "app.services.enrollment_state_sync.enrollment_state_sync",
                "schedule": 300.0,
                "options": {"queue": "default"},
            },
            "phase-4-5-auto-fire": {
                # M10: enqueue discovery-prep packs for deals that hit
                # ``initial_call_scheduled``. Pack generator (M11) is enqueued
                # via ``app.tasks.pack_generation.generate_pack``.
                "task": ("app.services.deal_phase_4_5_auto_fire_task.phase_4_5_auto_fire"),
                "schedule": float(settings.cron_phase_4_5_auto_fire_seconds),
                "options": {"queue": "default"},
            },
            "auto-archive-trigger-check": {
                # M10: archive deals where all 3 close-gate fields are set.
                # The ``brand_deal`` closing-row write ships in M16.
                "task": ("app.services.deal_auto_archive_task.auto_archive_trigger_check"),
                "schedule": float(settings.cron_auto_archive_trigger_check_seconds),
                "options": {"queue": "default"},
            },
            # M7.7 — monthly Phase 4 signal-overlay fan-out for active talents.
            # Gated by settings.discovery_phase_4_monthly_enabled — when False
            # the beat entry stays but the task body no-ops via the active-set
            # query returning [] for everyone.
            "discovery-phase-4-monthly": {
                "task": ("app.services.discovery_phase_4_monthly.fan_out_to_active_talents"),
                # ~30 days. Configurable per agency via env if needed.
                "schedule": 30 * 24 * 60 * 60,
                "options": {"queue": "default"},
            },
        },
    )

    return celery_app


app: Celery = _build_app()


@worker_process_init.connect
def _init_taxonomies_per_worker(**_kwargs: Any) -> None:  # pyright: ignore[reportUnusedFunction]
    """Load the taxonomy singleton in each forked worker process.

    The FastAPI app does this in its lifespan; Celery workers don't run the
    lifespan, so the discovery + contact-enrichment orchestrators crash with
    "Taxonomies not initialised" without this hook. Fires once per worker
    process (prefork model).
    """
    from app.utils.taxonomies import init_taxonomies

    init_taxonomies()
