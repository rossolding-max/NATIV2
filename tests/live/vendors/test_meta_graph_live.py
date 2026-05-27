"""Live smoke test for the Meta Graph client. Env-gated.

Token-bearing endpoints can't run without an interactive OAuth flow; this
test only verifies the authorize-URL composition against the live host.
"""

from __future__ import annotations

import os

import pytest

from app.vendors.meta_graph import MetaGraphClient

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (os.getenv("META_APP_ID") and os.getenv("META_APP_SECRET")),
        reason="META_APP_ID / META_APP_SECRET not set; live test skipped.",
    ),
]


def test_live__meta_graph__authorize_url_uses_real_credentials() -> None:
    client = MetaGraphClient()
    url = client.build_authorize_url(
        redirect_uri="https://example.invalid/callback", state="live-smoke"
    )
    # Just confirm the URL is well-formed against the configured app id.
    expected_client_id = os.environ["META_APP_ID"]
    assert f"client_id={expected_client_id}" in url
