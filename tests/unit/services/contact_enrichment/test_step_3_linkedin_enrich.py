"""Step 3 — LinkedIn profile enrichment."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.contact_enrichment import step_3_linkedin_enrich
from app.services.contact_enrichment._models import EnrichedContact


def _contact(
    *, name: str = "A", linkedin_url: str | None = None, title: str | None = None
) -> EnrichedContact:
    return EnrichedContact(
        contact_id=f"bc_{name.lower()}",
        brand_id="gymshark",
        name=name,
        title=title,
        linkedin_url=linkedin_url,
    )


@pytest.mark.asyncio
async def test_unit__step_3__no_linkedin_url_no_op() -> None:
    client = MagicMock()
    contacts = await step_3_linkedin_enrich.run(
        contacts=[_contact(name="X")], linkedin_client=client
    )
    assert contacts[0].sources == []  # no LinkedIn source added
    client.get_profile_by_url.assert_not_called()


@pytest.mark.asyncio
async def test_unit__step_3__enriches_contact_with_linkedin() -> None:
    client = MagicMock()
    client.get_profile_by_url = AsyncMock(
        return_value={"headline": "VP Marketing", "location": "London, UK"}
    )
    contact = _contact(name="A", linkedin_url="https://linkedin.com/in/a")
    contacts = await step_3_linkedin_enrich.run(contacts=[contact], linkedin_client=client)
    assert contacts[0].title == "VP Marketing"  # backfilled from LI headline
    assert contacts[0].location == {"city": "London, UK"}
    assert any(s["step"] == "step_3_linkedin_enrich" for s in contacts[0].sources)


@pytest.mark.asyncio
async def test_unit__step_3__doesnt_overwrite_existing_title() -> None:
    """Apollo title is canonical; LinkedIn only backfills."""
    client = MagicMock()
    client.get_profile_by_url = AsyncMock(return_value={"headline": "LinkedIn-only headline"})
    contact = _contact(name="A", linkedin_url="https://x", title="Apollo title")
    contacts = await step_3_linkedin_enrich.run(contacts=[contact], linkedin_client=client)
    assert contacts[0].title == "Apollo title"


@pytest.mark.asyncio
async def test_unit__step_3__linkedin_error_failsoft_continues() -> None:
    """An exception on one contact shouldn't kill enrichment for the others."""
    client = MagicMock()
    call_n = {"i": 0}

    async def _maybe_fail(url: str) -> dict[str, Any]:
        call_n["i"] += 1
        if call_n["i"] == 1:
            raise RuntimeError("LinkedIn rate limited")
        return {"headline": "VP Marketing"}

    client.get_profile_by_url = _maybe_fail
    contacts = await step_3_linkedin_enrich.run(
        contacts=[
            _contact(name="A", linkedin_url="https://1"),
            _contact(name="B", linkedin_url="https://2"),
        ],
        linkedin_client=client,
    )
    assert contacts[0].sources == []  # first failed
    assert any(s["step"] == "step_3_linkedin_enrich" for s in contacts[1].sources)
