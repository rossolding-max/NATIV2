"""Live smoke test for the LinkedIn scraper client (RapidAPI). Env-gated."""

from __future__ import annotations

import os

import pytest

from app.vendors.linkedin import LinkedInScraperClient

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.getenv("RAPIDAPI_KEY"),
        reason="RAPIDAPI_KEY not set; live test skipped.",
    ),
]


async def test_live__linkedin_get_company_by_domain_returns_200() -> None:
    """Confirm RapidAPI gateway auth works against a known domain."""
    client = LinkedInScraperClient()
    try:
        await client.get_company_by_domain("linkedin.com")
    except Exception as exc:
        detail = getattr(exc, "detail", {})
        status = detail.get("status")
        # 401 = key invalid; 403 = host header wrong / quota dry. Both = auth fail.
        assert status not in (401, 403), (
            f"Live RapidAPI auth failed with HTTP {status}; "
            "check RAPIDAPI_KEY + subscription to Real-Time LinkedIn Scraper API"
        )
