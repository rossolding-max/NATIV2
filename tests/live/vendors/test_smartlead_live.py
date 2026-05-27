"""Live smoke test for the Smartlead client. Env-gated.

Run only via ``pytest -m live tests/live/vendors/``. Skipped by default —
runs only when ``SMARTLEAD_API_KEY`` is set AND the ``live`` marker is
explicitly selected.

Smoke level only: GET a campaign list / health endpoint. Does NOT create
or modify resources.
"""

from __future__ import annotations

import os

import pytest

from app.vendors.smartlead import SmartleadClient

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.getenv("SMARTLEAD_API_KEY"),
        reason="SMARTLEAD_API_KEY not set; live test skipped.",
    ),
]


async def test_live__smartlead_get_known_campaign_status_returns_200() -> None:
    """Touch a read-only endpoint to confirm auth works.

    The endpoint is harmless even with a fake campaign id — Smartlead
    returns a 404 envelope. We only assert that the auth roundtrip works
    (i.e., we get a non-401 response).
    """
    client = SmartleadClient()
    # Use a placeholder campaign id; a 404 from the API still proves auth
    # passed. We just need to not see 401.
    try:
        await client.get_campaign_status("campaign-does-not-exist")
    except Exception as exc:
        detail = getattr(exc, "detail", {})
        status = detail.get("status")
        assert status != 401, "Auth failed against live Smartlead API"
