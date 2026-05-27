"""Hardening tests for ``app.config.Settings``.

Verifies the spec-mandated boot guards actually refuse invalid configuration
(per ``docs/auth_and_authorization.md`` + ``CLAUDE.md`` strict don'ts).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings

_VALID_ENV: Mapping[str, str] = {
    "POSTGRES_PASSWORD": "test-pg-pw",
    "DB_MASTER_KEY": "test-master-key-32-bytes-base64==",
    "ANTHROPIC_API_KEY": "sk-ant-test-stub",
}


def _make(monkeypatch: pytest.MonkeyPatch, env: Mapping[str, str | None]) -> Settings:
    """Construct Settings under a hermetic monkeypatched env.

    ``None`` values delete the env var. Anything not mentioned is unset.
    """
    # Wipe everything the .env / OS might leak in.
    for k in [
        *_VALID_ENV.keys(),
        "NATIV2_BIND_HOST",
        "NATIV2_EXTERNAL_BIND_CONFIRMED",
        "LLM_BUDGET_DAILY_USD",
        "LLM_BUDGET_HARD_KILL_DAILY_USD",
    ]:
        monkeypatch.delenv(k, raising=False)

    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)

    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_unit__settings_refuses_missing_postgres_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env: dict[str, Any] = dict(_VALID_ENV)
    del env["POSTGRES_PASSWORD"]
    with pytest.raises(ValidationError, match="postgres_password"):
        _make(monkeypatch, env)


def test_unit__settings_refuses_missing_db_master_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env: dict[str, Any] = dict(_VALID_ENV)
    del env["DB_MASTER_KEY"]
    with pytest.raises(ValidationError, match="db_master_key"):
        _make(monkeypatch, env)


def test_unit__settings_refuses_missing_anthropic_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env: dict[str, Any] = dict(_VALID_ENV)
    del env["ANTHROPIC_API_KEY"]
    with pytest.raises(ValidationError, match="anthropic_api_key"):
        _make(monkeypatch, env)


def test_unit__settings_refuses_external_bind_without_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env: dict[str, str] = dict(_VALID_ENV) | {"NATIV2_BIND_HOST": "0.0.0.0"}
    with pytest.raises(ValidationError, match="EXTERNAL_BIND_CONFIRMED"):
        _make(monkeypatch, env)


def test_unit__settings_accepts_external_bind_with_explicit_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env: dict[str, str] = dict(_VALID_ENV) | {
        "NATIV2_BIND_HOST": "0.0.0.0",
        "NATIV2_EXTERNAL_BIND_CONFIRMED": "true",
    }
    s = _make(monkeypatch, env)
    assert s.nativ2_bind_host == "0.0.0.0"
    assert s.nativ2_external_bind_confirmed is True


def test_unit__settings_refuses_inverted_llm_budgets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env: dict[str, str] = dict(_VALID_ENV) | {
        "LLM_BUDGET_DAILY_USD": "100",
        "LLM_BUDGET_HARD_KILL_DAILY_USD": "50",
    }
    with pytest.raises(ValidationError, match="HARD_KILL_DAILY_USD"):
        _make(monkeypatch, env)


def test_unit__settings_defaults_safe_for_local_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify v0.1 sane defaults — 127.0.0.1 bind, S3 MinIO local, etc."""
    s = _make(monkeypatch, _VALID_ENV)
    assert s.nativ2_bind_host == "127.0.0.1"
    assert s.nativ2_bind_port == 8000
    assert s.nativ2_environment == "development"
    assert str(s.s3_endpoint_url).startswith("http://127.0.0.1:9000")
    assert s.s3_bucket == "nativ2-v0-1-local"
    assert s.celery_worker_concurrency_default == 4
    assert s.celery_worker_concurrency_llm_heavy == 2


def test_unit__settings_derived_dsns_contain_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Async + sync DSNs include the user/pw/host/port/db parts."""
    s = _make(monkeypatch, _VALID_ENV)
    dsn = s.database_url_async
    assert dsn.startswith("postgresql+asyncpg://")
    assert "nativ2:" in dsn  # user
    assert "test-pg-pw" in dsn  # password (URL-encoded)
    assert "127.0.0.1:5432" in dsn
    assert dsn.endswith("/nativ2")

    sync_dsn = s.database_url_sync
    assert sync_dsn.startswith("postgresql+psycopg://")
