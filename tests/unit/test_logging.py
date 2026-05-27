"""Hardening tests for structlog config + PII redaction.

Verifies the redactor strips known PII keys at log emission time so secrets
don't leak to stdout / Sentry / shipped JSON.
"""

from __future__ import annotations

import io
import json
import logging
from typing import Any

import structlog

from app.utils.logging import _PII_KEYS, _redact_pii, init_logging  # type: ignore[attr-defined]


def test_unit__redactor_strips_documented_pii_keys() -> None:
    """Every key in ``_PII_KEYS`` is replaced by ``[redacted]``."""
    event: dict[str, Any] = {
        "email": "alice@example.com",
        "access_token": "Bearer abc",
        "memo_content": "private notes",
        "talent_name": "Riley Carter",
        "non_pii_key": "kept",
    }
    out = _redact_pii(None, "info", event)
    assert out["email"] == "[redacted]"
    assert out["access_token"] == "[redacted]"
    assert out["memo_content"] == "[redacted]"
    assert out["talent_name"] == "[redacted]"
    assert out["non_pii_key"] == "kept"


def test_unit__redactor_case_insensitive() -> None:
    """Upper-case PII keys are still redacted."""
    event: dict[str, Any] = {"EMAIL": "x@y.z", "ACCESS_TOKEN": "Bearer y"}
    out = _redact_pii(None, "info", event)
    assert out["EMAIL"] == "[redacted]"
    assert out["ACCESS_TOKEN"] == "[redacted]"


def test_unit__pii_key_set_contains_documented_keys() -> None:
    """Spot-check the redactor covers the documented PII keys."""
    must_redact = {
        "email",
        "access_token",
        "refresh_token",
        "password",
        "client_secret",
        "api_key",
        "db_master_key",
        "memo_content",
        "contract_text",
        "talent_name",
        "brand_name",
        "legal_name",
    }
    assert must_redact.issubset(_PII_KEYS)


def test_unit__init_logging_idempotent() -> None:
    """Calling init_logging multiple times must not raise."""
    init_logging()
    init_logging()  # second call is a no-op
    log = structlog.get_logger("test")
    log.info("smoke")


def test_unit__json_output_contains_redacted_values(
    monkeypatch: Any,
) -> None:
    """End-to-end: a logger call with PII fields emits JSON with redactions."""
    buf = io.StringIO()

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact_pii,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=buf),
        cache_logger_on_first_use=False,
    )

    log = structlog.get_logger("test")
    log.info(
        "user_signed_in",
        email="alice@example.com",
        access_token="secret",
        normal_field="ok",
    )

    line = buf.getvalue().strip()
    parsed = json.loads(line)
    assert parsed["email"] == "[redacted]"
    assert parsed["access_token"] == "[redacted]"
    assert parsed["normal_field"] == "ok"
    assert parsed["event"] == "user_signed_in"

    # Reset to project default to avoid bleed into later tests.
    init_logging()
