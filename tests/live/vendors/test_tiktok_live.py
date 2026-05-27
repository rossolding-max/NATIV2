"""Live smoke test for the TikTok client. Env-gated."""

from __future__ import annotations

import os

import pytest

from app.vendors.tiktok import TikTokClient, generate_pkce_pair

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (os.getenv("TIKTOK_CLIENT_KEY") and os.getenv("TIKTOK_CLIENT_SECRET")),
        reason="TIKTOK_CLIENT_KEY / SECRET not set; live test skipped.",
    ),
]


def test_live__tiktok__authorize_url_includes_pkce_challenge() -> None:
    client = TikTokClient()
    _, challenge = generate_pkce_pair()
    url = client.build_authorize_url(
        redirect_uri="https://example.invalid/callback",
        state="live-smoke",
        code_challenge=challenge,
    )
    expected_client_key = os.environ["TIKTOK_CLIENT_KEY"]
    assert f"client_id={expected_client_key}" in url
    assert "code_challenge_method=S256" in url
