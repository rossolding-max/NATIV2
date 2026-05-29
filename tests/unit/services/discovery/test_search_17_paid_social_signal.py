"""Search 17 — paid social ad signal unit tests.

Mocks the Meta + TikTok vendor clients so no network calls fire. Verifies:
- gate check (settings.enable_search_17_paid_social=False -> no candidates)
- single-platform vs multi-platform weighting
- min_active_ads threshold filtering
- max_industries cost cap
- existing brand_industry_map normalisation
- vendor exception is swallowed (search degrades to empty list)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.discovery import search_17_paid_social_signal as s17

_BIM_BASE: dict[str, Any] = {
    "brands": [
        {
            "id": "alo-yoga",
            "name": "Alo Yoga",
            "aliases": ["alo"],
            "industry_ids": ["activewear-performance"],
        },
    ]
}


@pytest.fixture(autouse=True)
def _enable_search_17(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    """Most tests run with the gate on; the gate-off test overrides locally."""
    from app.config import settings

    monkeypatch.setattr(settings, "enable_search_17_paid_social", True)
    monkeypatch.setattr(settings, "paid_social_min_active_ads", 5)
    monkeypatch.setattr(settings, "paid_social_max_industries_per_run", 3)
    monkeypatch.setattr(settings, "meta_ads_default_countries", ["US"])


def _make_meta_mock(per_industry_returns: dict[str, dict[str, Any]]) -> MagicMock:
    """Return a mock MetaAdsClient that maps industry_id -> per-brand dict."""
    client = MagicMock()

    async def _count(*, search_terms: str, countries: list[str], days_back: int = 30):
        _ = countries, days_back
        return per_industry_returns.get(search_terms.replace(" ", "-"), {})

    client.count_active_ads_per_advertiser = AsyncMock(side_effect=_count)
    return client


def _make_tiktok_mock(returns: dict[str, dict[str, Any]]) -> MagicMock:
    client = MagicMock()

    async def _count(
        *,
        industries: list[str],
        region: str,
        period_days: int = 30,
        per_industry_limit: int = 50,
    ):
        _ = industries, region, period_days, per_industry_limit
        return returns

    client.count_active_advertisers_per_industry = AsyncMock(side_effect=_count)
    return client


@pytest.mark.asyncio
async def test_unit__s17__gate_off_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "enable_search_17_paid_social", False)
    out = await s17.run(top_industry_ids=["activewear-performance"], brand_industry_map=_BIM_BASE)
    assert out == []


@pytest.mark.asyncio
async def test_unit__s17__no_industries_returns_empty() -> None:
    out = await s17.run(top_industry_ids=[], brand_industry_map=_BIM_BASE)
    assert out == []


@pytest.mark.asyncio
async def test_unit__s17__multi_platform_brand_gets_higher_weight() -> None:
    meta = _make_meta_mock(
        {
            "activewear-performance": {
                "Alo Yoga": {"ad_count": 12, "page_id": "p_alo", "industries": []},
            }
        }
    )
    tiktok = _make_tiktok_mock(
        {
            "Alo Yoga": {"ad_count": 8, "industries": ["activewear-performance"]},
        }
    )

    with (
        patch("app.vendors.meta_ads.MetaAdsClient", return_value=meta),
        patch("app.vendors.tiktok_creative_center.TikTokCreativeCenterClient", return_value=tiktok),
    ):
        out = await s17.run(
            top_industry_ids=["activewear-performance"],
            brand_industry_map=_BIM_BASE,
        )

    assert len(out) == 1
    cand = out[0]
    assert cand.brand_id == "alo-yoga"  # matched against the seed map
    assert cand.search_tag == s17.MULTI_PLATFORM_TAG
    assert cand.weight == pytest.approx(s17.MULTI_PLATFORM_WEIGHT)
    assert "meta_active_ads=12" in cand.note
    assert "tiktok_active_creatives=8" in cand.note


@pytest.mark.asyncio
async def test_unit__s17__single_platform_meta_only() -> None:
    meta = _make_meta_mock(
        {
            "activewear-performance": {
                "Gymshark": {"ad_count": 9, "page_id": "p_gs", "industries": []},
            }
        }
    )
    tiktok = _make_tiktok_mock({})

    with (
        patch("app.vendors.meta_ads.MetaAdsClient", return_value=meta),
        patch("app.vendors.tiktok_creative_center.TikTokCreativeCenterClient", return_value=tiktok),
    ):
        out = await s17.run(
            top_industry_ids=["activewear-performance"],
            brand_industry_map=_BIM_BASE,
        )

    assert len(out) == 1
    assert out[0].brand_name == "Gymshark"
    assert out[0].search_tag == s17.SINGLE_PLATFORM_TAG
    assert out[0].weight == pytest.approx(s17.SINGLE_PLATFORM_WEIGHT)
    assert "meta_active_ads=9" in out[0].note


@pytest.mark.asyncio
async def test_unit__s17__single_platform_tiktok_only() -> None:
    meta = _make_meta_mock({})
    tiktok = _make_tiktok_mock(
        {
            "Rhode Skin": {"ad_count": 11, "industries": ["beauty-skincare"]},
        }
    )

    with (
        patch("app.vendors.meta_ads.MetaAdsClient", return_value=meta),
        patch("app.vendors.tiktok_creative_center.TikTokCreativeCenterClient", return_value=tiktok),
    ):
        out = await s17.run(
            top_industry_ids=["beauty-skincare"],
            brand_industry_map=_BIM_BASE,
        )

    assert len(out) == 1
    assert out[0].brand_name == "Rhode Skin"
    assert out[0].search_tag == s17.SINGLE_PLATFORM_TAG


@pytest.mark.asyncio
async def test_unit__s17__threshold_drops_low_ad_count_brands() -> None:
    """Brands with < paid_social_min_active_ads are filtered out."""
    meta = _make_meta_mock(
        {
            "activewear-performance": {
                "Alo Yoga": {"ad_count": 4, "page_id": "p_alo", "industries": []},
                "Gymshark": {"ad_count": 9, "page_id": "p_gs", "industries": []},
            }
        }
    )
    tiktok = _make_tiktok_mock({})

    with (
        patch("app.vendors.meta_ads.MetaAdsClient", return_value=meta),
        patch("app.vendors.tiktok_creative_center.TikTokCreativeCenterClient", return_value=tiktok),
    ):
        out = await s17.run(
            top_industry_ids=["activewear-performance"],
            brand_industry_map=_BIM_BASE,
        )

    names = {c.brand_name for c in out}
    assert "Alo Yoga" not in names  # 4 < threshold 5
    assert "Gymshark" in names


@pytest.mark.asyncio
async def test_unit__s17__caps_industries_per_run() -> None:
    """max_industries cap means only N industries get queried."""
    calls: list[str] = []

    async def _meta_count(
        *, search_terms: str, countries: list[str], days_back: int = 30
    ) -> dict[str, Any]:
        _ = countries, days_back
        calls.append(search_terms)
        return {}

    meta = MagicMock()
    meta.count_active_ads_per_advertiser = AsyncMock(side_effect=_meta_count)
    tiktok = _make_tiktok_mock({})

    with (
        patch("app.vendors.meta_ads.MetaAdsClient", return_value=meta),
        patch("app.vendors.tiktok_creative_center.TikTokCreativeCenterClient", return_value=tiktok),
    ):
        await s17.run(
            top_industry_ids=["a", "b", "c", "d", "e"],
            brand_industry_map=_BIM_BASE,
            max_industries=2,
        )

    assert len(calls) == 2  # cap honoured


@pytest.mark.asyncio
async def test_unit__s17__meta_failure_softfallbacks_to_tiktok_only() -> None:
    """If MetaAdsClient init raises, we still process the TikTok side."""
    tiktok = _make_tiktok_mock({"Tiktok Brand": {"ad_count": 7, "industries": ["x"]}})

    def _meta_raises(*_args: Any, **_kwargs: Any) -> Any:
        from app.errors import IntegrationError

        raise IntegrationError("no meta token")

    with (
        patch("app.vendors.meta_ads.MetaAdsClient", side_effect=_meta_raises),
        patch("app.vendors.tiktok_creative_center.TikTokCreativeCenterClient", return_value=tiktok),
    ):
        out = await s17.run(
            top_industry_ids=["x"],
            brand_industry_map=_BIM_BASE,
        )

    assert len(out) == 1
    assert out[0].brand_name == "Tiktok Brand"


@pytest.mark.asyncio
async def test_unit__s17__alias_match_resolves_existing_brand_id() -> None:
    """Vendor returns 'alo' (the alias); seed-map normalisation finds 'Alo Yoga'."""
    meta = _make_meta_mock(
        {
            "activewear-performance": {
                "alo": {"ad_count": 11, "page_id": "p_alo", "industries": []},
            }
        }
    )
    tiktok = _make_tiktok_mock({})

    with (
        patch("app.vendors.meta_ads.MetaAdsClient", return_value=meta),
        patch("app.vendors.tiktok_creative_center.TikTokCreativeCenterClient", return_value=tiktok),
    ):
        out = await s17.run(
            top_industry_ids=["activewear-performance"],
            brand_industry_map=_BIM_BASE,
        )

    assert len(out) == 1
    assert out[0].brand_id == "alo-yoga"  # canonical id from seed map
    assert out[0].brand_name == "Alo Yoga"  # display name from seed map


@pytest.mark.asyncio
async def test_unit__s17__page_name_suffix_stripped_for_matching() -> None:
    """'Alo Yoga - Official' -> matches 'Alo Yoga' in the seed map."""
    meta = _make_meta_mock(
        {
            "activewear-performance": {
                "Alo Yoga - Official": {"ad_count": 7, "page_id": "p", "industries": []},
            }
        }
    )
    tiktok = _make_tiktok_mock({})

    with (
        patch("app.vendors.meta_ads.MetaAdsClient", return_value=meta),
        patch("app.vendors.tiktok_creative_center.TikTokCreativeCenterClient", return_value=tiktok),
    ):
        out = await s17.run(
            top_industry_ids=["activewear-performance"],
            brand_industry_map=_BIM_BASE,
        )

    assert len(out) == 1
    assert out[0].brand_id == "alo-yoga"


@pytest.mark.asyncio
async def test_unit__s17__net_new_brand_gets_slugified_id() -> None:
    """Brand not in the seed map gets a deterministic slug from its name."""
    meta = _make_meta_mock(
        {
            "activewear-performance": {
                "BrandNotInMap": {"ad_count": 6, "page_id": "p", "industries": []},
            }
        }
    )
    tiktok = _make_tiktok_mock({})

    with (
        patch("app.vendors.meta_ads.MetaAdsClient", return_value=meta),
        patch("app.vendors.tiktok_creative_center.TikTokCreativeCenterClient", return_value=tiktok),
    ):
        out = await s17.run(
            top_industry_ids=["activewear-performance"],
            brand_industry_map=_BIM_BASE,
        )

    assert len(out) == 1
    assert out[0].brand_id == "brandnotinmap"


def test_unit__s17__weights_module_constants() -> None:
    """Pin the v1 weight constants so accidental tuning shows up in review."""
    assert pytest.approx(0.20) == s17.SINGLE_PLATFORM_WEIGHT
    assert pytest.approx(0.30) == s17.MULTI_PLATFORM_WEIGHT
    assert s17.SINGLE_PLATFORM_TAG == "paid_social_active"
    assert s17.MULTI_PLATFORM_TAG == "paid_social_active_multi"
