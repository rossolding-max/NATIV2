"""Structured logging setup. See ``docs/code_conventions.md`` § 5.

Configures structlog with:

- Context-var binding (``request_id``, ``agency_id``, ``agent_id`` etc.).
- ISO 8601 UTC timestamps.
- PII redaction (strips known sensitive keys).
- JSON output in test/production; pretty console in development.
"""

from __future__ import annotations

import logging
from typing import Any

import structlog
from structlog.contextvars import merge_contextvars
from structlog.types import EventDict, Processor, WrappedLogger

from app.config import settings

# Keys whose values are PII or secrets. Always redacted before logs leave the
# process. See CLAUDE.md "Strict don'ts" (no PII in logs).
_PII_KEYS: frozenset[str] = frozenset(
    {
        # Identity
        "email",
        "email_address",
        "legal_name",
        "talent_name",
        "brand_name",
        "first_name",
        "last_name",
        "full_name",
        # Content / messages
        "contract_text",
        "memo_content",
        "pitch_body",
        "memo_body",
        # Secrets
        "access_token",
        "refresh_token",
        "password",
        "client_secret",
        "api_key",
        "db_master_key",
        "webhook_secret",
        "secret",
    }
)

_REDACTED: str = "[redacted]"


def _redact_pii(
    _logger: WrappedLogger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Replace any PII-keyed value with ``[redacted]`` before rendering."""
    for key in list(event_dict.keys()):
        if key.lower() in _PII_KEYS:
            event_dict[key] = _REDACTED
    return event_dict


def init_logging() -> None:
    """Configure structlog + stdlib logging.

    Idempotent — safe to call multiple times (e.g. once in lifespan + once
    from a Celery worker process).
    """
    is_dev = settings.nativ2_environment == "development"

    renderer: Processor = (
        structlog.dev.ConsoleRenderer(colors=True)
        if is_dev
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            _redact_pii,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Quiet noisy libraries — they go through stdlib logging.
    for noisy in ("urllib3", "botocore", "boto3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> Any:
    """Module-level logger getter. Use as: ``log = get_logger(__name__)``."""
    return structlog.get_logger(name)
