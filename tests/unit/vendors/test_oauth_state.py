"""Unit tests for ``app.vendors._oauth_state``."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.vendors import _oauth_state
from app.vendors._oauth_state import (
    build_authorize_url,
    generate_state,
    store_state,
    validate_and_consume_state,
)


@pytest.fixture(autouse=True)
def _reset_redis() -> Any:  # pyright: ignore[reportUnusedFunction]
    _oauth_state.reset_client_for_tests()
    yield
    _oauth_state.reset_client_for_tests()


def test_unit__generate_state__produces_unique_urlsafe_strings() -> None:
    a = generate_state()
    b = generate_state()
    assert a != b
    # token_urlsafe is base64url; no padding, no `+/`.
    for ch in a + b:
        assert ch.isalnum() or ch in {"-", "_"}


async def test_unit__store_state__sets_payload_with_ttl() -> None:
    mock_client = AsyncMock()
    mock_client.setex = AsyncMock(return_value=True)
    with patch.object(_oauth_state, "get_redis_client", return_value=mock_client):
        await store_state(
            "abc",
            talent_id="t_1",
            platform="tiktok",
            code_verifier="verifier-x",
            ttl_seconds=600,
        )
    mock_client.setex.assert_awaited_once()
    call_args = mock_client.setex.await_args_list[0].args
    assert call_args[0] == "oauth_state:abc"
    assert call_args[1] == 600
    payload = json.loads(call_args[2])
    assert payload == {
        "talent_id": "t_1",
        "platform": "tiktok",
        "code_verifier": "verifier-x",
    }


async def test_unit__validate_and_consume__returns_payload_then_deletes() -> None:
    """The pipeline runs GET + DELETE atomically; the consume is one-shot."""
    stored = json.dumps({"talent_id": "t_42", "platform": "meta", "code_verifier": None})
    pipe = MagicMock()
    pipe.get = MagicMock()
    pipe.delete = MagicMock()
    pipe.execute = AsyncMock(return_value=[stored, 1])

    mock_client = MagicMock()
    mock_client.pipeline = MagicMock(return_value=pipe)

    with patch.object(_oauth_state, "get_redis_client", return_value=mock_client):
        result = await validate_and_consume_state("abc")

    assert result == {"talent_id": "t_42", "platform": "meta", "code_verifier": None}
    pipe.get.assert_called_with("oauth_state:abc")
    pipe.delete.assert_called_with("oauth_state:abc")


async def test_unit__validate_missing_state__returns_none() -> None:
    pipe = MagicMock()
    pipe.get = MagicMock()
    pipe.delete = MagicMock()
    pipe.execute = AsyncMock(return_value=[None, 0])
    mock_client = MagicMock()
    mock_client.pipeline = MagicMock(return_value=pipe)
    with patch.object(_oauth_state, "get_redis_client", return_value=mock_client):
        assert await validate_and_consume_state("missing") is None


def test_unit__build_authorize_url__joins_scopes_and_appends_extra() -> None:
    url = build_authorize_url(
        base_url="https://example.com/oauth",
        client_id="cid",
        redirect_uri="https://app.example.com/callback",
        scopes=["read", "write"],
        state="abc",
        extra={"code_challenge": "cc", "code_challenge_method": "S256"},
    )
    assert url.startswith("https://example.com/oauth?")
    # Scopes joined with space, then URL-encoded as +.
    assert "scope=read+write" in url
    assert "client_id=cid" in url
    assert "state=abc" in url
    assert "code_challenge=cc" in url
    assert "code_challenge_method=S256" in url
