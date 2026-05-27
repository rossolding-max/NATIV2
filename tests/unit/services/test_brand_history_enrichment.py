"""Unit tests for the Step 6 brand→industry resolver."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import brand_history_enrichment as bhe


@pytest.fixture(autouse=True)
def _reset_cache() -> object:  # pyright: ignore[reportUnusedFunction]
    bhe.reset_cache_for_tests()
    yield
    bhe.reset_cache_for_tests()


async def test_unit__resolve_industry__exact_match() -> None:
    fake_map = {"acme": "consumer-electronics"}
    with patch.object(bhe, "_load_brand_industry_map", return_value=fake_map):
        result = await bhe.resolve_industry("Acme")
    assert result.industry_id == "consumer-electronics"
    assert result.source == "exact_match"
    assert result.confidence == 1.0


async def test_unit__resolve_industry__case_insensitive_exact_match() -> None:
    fake_map = {"acme": "consumer-electronics"}
    with patch.object(bhe, "_load_brand_industry_map", return_value=fake_map):
        result = await bhe.resolve_industry("  ACME  ")
    assert result.industry_id == "consumer-electronics"


async def test_unit__resolve_industry__unknown_falls_to_exa() -> None:
    fake_map: dict[str, str] = {}
    with patch.object(bhe, "_load_brand_industry_map", return_value=fake_map):
        result = await bhe.resolve_industry("UnknownBrand")
    assert result.industry_id is None
    assert result.source == "unknown"
    assert result.confidence == 0.0


async def test_unit__resolve_industry__empty_name__returns_unknown() -> None:
    result = await bhe.resolve_industry("   ")
    assert result.industry_id is None
    assert result.source == "unknown"


def test_unit__merge_inference_into_brands__applies_industry_id() -> None:
    inferences = [
        bhe.IndustryInference(
            brand_name="Acme", industry_id="food", confidence=0.95, source="exact_match"
        )
    ]
    brands = [{"brand": "Acme", "fee": 5000}, {"brand": "Other"}]
    merged = bhe.merge_inference_into_brands(brands, inferences)
    assert merged[0]["industry_id"] == "food"
    assert merged[0]["industry_inference_source"] == "exact_match"
    assert "industry_id" not in merged[1]


def test_unit__merge_inference__skips_unknown_inferences() -> None:
    inferences = [
        bhe.IndustryInference(brand_name="Acme", industry_id=None, confidence=0.0, source="unknown")
    ]
    brands = [{"brand": "Acme"}]
    merged = bhe.merge_inference_into_brands(brands, inferences)
    assert "industry_id" not in merged[0]
