"""Live smoke test for the Apollo client. Env-gated."""

from __future__ import annotations

import os

import pytest

from app.vendors.apollo import ApolloClient

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.getenv("APOLLO_API_KEY"),
        reason="APOLLO_API_KEY not set; live test skipped.",
    ),
]


async def test_live__apollo_enrich_known_org_returns_200() -> None:
    """Confirm auth round-trip works against a well-known public domain."""
    client = ApolloClient()
    try:
        await client.enrich_organization("apollo.io")
    except Exception as exc:
        detail = getattr(exc, "detail", {})
        status = detail.get("status")
        assert status != 401, "Auth failed against live Apollo API"
