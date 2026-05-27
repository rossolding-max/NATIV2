"""Sentry initialisation. See ``docs/architecture.md`` § 7.

No-op if ``SENTRY_DSN`` is unset (development default).

``before_send`` redacts the same PII keys the structlog redactor uses, so
event payloads sent to Sentry don't carry secrets.
"""

from __future__ import annotations

from typing import Any

import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.redis import RedisIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from app.config import settings
from app.utils.logging import _PII_KEYS  # type: ignore[attr-defined]

_REDACTED_SUBSTITUTE = "[redacted]"


def _scrub_pii(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
    """Strip known-PII keys from event payloads before sending to Sentry."""
    extra = event.get("extra", {})
    if isinstance(extra, dict):
        for key in list(extra.keys()):
            if key.lower() in _PII_KEYS:
                extra[key] = _REDACTED_SUBSTITUTE
    tags = event.get("tags", {})
    if isinstance(tags, dict):
        for key in list(tags.keys()):
            if key.lower() in _PII_KEYS:
                tags[key] = _REDACTED_SUBSTITUTE
    return event


def init_sentry() -> None:
    """Initialise Sentry SDK if a DSN is configured. Idempotent."""
    if settings.sentry_dsn is None:
        return

    sentry_sdk.init(
        dsn=str(settings.sentry_dsn),
        environment=settings.sentry_environment,
        release=settings.nativ2_version,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        before_send=_scrub_pii,  # type: ignore[arg-type]
        integrations=[
            FastApiIntegration(),
            SqlalchemyIntegration(),
            RedisIntegration(),
            CeleryIntegration(),
            AsyncioIntegration(),
        ],
        send_default_pii=False,
    )
