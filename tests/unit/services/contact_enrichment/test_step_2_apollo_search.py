"""Step 2 — Apollo employee search."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.contact_enrichment import step_2_apollo_search


def _person(
    *,
    apollo_id: str,
    name: str,
    title: str = "VP Marketing",
    email: str | None = None,
    email_status: str | None = None,
    linkedin_url: str | None = None,
    seniority: str | None = "vp",
) -> dict[str, Any]:
    return {
        "id": apollo_id,
        "name": name,
        "title": title,
        "email": email,
        "email_status": email_status,
        "linkedin_url": linkedin_url,
        "seniority": seniority,
    }


@pytest.mark.asyncio
async def test_unit__step_2__single_title_produces_contact() -> None:
    client = MagicMock()
    client.search_people = AsyncMock(
        return_value={"people": [_person(apollo_id="ap_1", name="Alex Smith")]}
    )
    contacts = await step_2_apollo_search.run(
        brand_id="gymshark",
        domain="gymshark.com",
        target_titles=["VP Marketing"],
        apollo_client=client,
    )
    assert len(contacts) == 1
    assert contacts[0].name == "Alex Smith"
    assert contacts[0].title == "VP Marketing"
    assert contacts[0].brand_id == "gymshark"
    assert contacts[0].sources[0]["step"] == "step_2_apollo_search"


@pytest.mark.asyncio
async def test_unit__step_2__dedupes_by_apollo_id_across_titles() -> None:
    """Same Apollo person returned for two different title queries -> one contact."""
    client = MagicMock()
    same_person = _person(apollo_id="ap_1", name="Alex Smith", title="VP Marketing")
    client.search_people = AsyncMock(return_value={"people": [same_person]})
    contacts = await step_2_apollo_search.run(
        brand_id="gymshark",
        domain="gymshark.com",
        target_titles=["VP Marketing", "Head of Brand"],
        apollo_client=client,
    )
    assert len(contacts) == 1
    assert client.search_people.call_count == 2  # two queries, one dedupe


@pytest.mark.asyncio
async def test_unit__step_2__max_candidates_caps_fan_out() -> None:
    """Once cap is hit, additional title queries don't run."""
    client = MagicMock()

    async def _alternate(**kwargs: Any) -> Any:
        title = (kwargs.get("titles") or ["X"])[0]
        return {"people": [_person(apollo_id=f"ap_{title}", name=f"Person {title}")]}

    client.search_people = _alternate
    contacts = await step_2_apollo_search.run(
        brand_id="gymshark",
        domain="gymshark.com",
        target_titles=["t1", "t2", "t3", "t4", "t5"],
        apollo_client=client,
        max_candidates=2,
    )
    assert len(contacts) == 2


@pytest.mark.asyncio
async def test_unit__step_2__empty_domain_returns_empty() -> None:
    client = MagicMock()
    contacts = await step_2_apollo_search.run(
        brand_id="gymshark",
        domain="",
        target_titles=["VP Marketing"],
        apollo_client=client,
    )
    assert contacts == []
    client.search_people.assert_not_called()


@pytest.mark.asyncio
async def test_unit__step_2__apollo_error_failsoft_continues() -> None:
    """An exception on one title shouldn't kill the whole run."""
    client = MagicMock()
    call_count = {"n": 0}

    async def _maybe_fail(**kwargs: Any) -> Any:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("Apollo down for this query")
        return {"people": [_person(apollo_id="ap_2", name="Beta")]}

    client.search_people = _maybe_fail
    contacts = await step_2_apollo_search.run(
        brand_id="gymshark",
        domain="gymshark.com",
        target_titles=["t1", "t2"],
        apollo_client=client,
    )
    assert len(contacts) == 1
    assert contacts[0].name == "Beta"


@pytest.mark.asyncio
async def test_unit__step_2__email_status_passed_through() -> None:
    client = MagicMock()
    client.search_people = AsyncMock(
        return_value={
            "people": [
                _person(
                    apollo_id="ap_1",
                    name="Verified Voe",
                    email="vv@example.com",
                    email_status="verified",
                )
            ]
        }
    )
    contacts = await step_2_apollo_search.run(
        brand_id="gymshark",
        domain="gymshark.com",
        target_titles=["VP Marketing"],
        apollo_client=client,
    )
    assert contacts[0].email_address == "vv@example.com"
    assert contacts[0].email_verification_status == "verified"


# ── M8.1 — broadened capture parameters ───────────────────────────


@pytest.mark.asyncio
async def test_unit__step_2_m81__per_page_is_100() -> None:
    """Apollo /people/search per_page bumped 10 → 100 in M8.1."""
    client = MagicMock()
    client.search_people = AsyncMock(return_value={"people": []})
    await step_2_apollo_search.run(
        brand_id="gymshark",
        domain="gymshark.com",
        target_titles=["marketing"],
        apollo_client=client,
    )
    # Verify the per_page arg passed to Apollo.
    _, kwargs = client.search_people.call_args
    assert kwargs["per_page"] == 100


@pytest.mark.asyncio
async def test_unit__step_2_m81__default_max_candidates_is_100() -> None:
    """The brand-level dedup cap bumped 12 → 100 to absorb broad pool."""
    assert step_2_apollo_search.DEFAULT_MAX_CANDIDATES == 100


@pytest.mark.asyncio
async def test_unit__step_2_m81__broad_keyword_titles_each_query_apollo() -> None:
    """Pass a 5-keyword title list; Apollo is queried once per keyword."""
    client = MagicMock()
    client.search_people = AsyncMock(return_value={"people": []})
    await step_2_apollo_search.run(
        brand_id="gymshark",
        domain="gymshark.com",
        target_titles=["marketing", "brand", "creator", "growth", "founder"],
        apollo_client=client,
    )
    assert client.search_people.call_count == 5
    queried_titles = [call.kwargs["titles"][0] for call in client.search_people.call_args_list]
    assert queried_titles == ["marketing", "brand", "creator", "growth", "founder"]
