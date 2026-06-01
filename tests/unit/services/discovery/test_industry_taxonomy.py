"""M7.7 — Top-level / sub-industry derivation tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services.discovery._industry_taxonomy import derive_top_level_and_sub_industry


def _mock_tax(parents: dict[str, str | None]) -> MagicMock:
    tax = MagicMock()
    tax.get_industry_parent.side_effect = lambda industry_id: parents.get(industry_id)  # pyright: ignore[reportUnknownLambdaType,reportUnknownArgumentType]
    return tax


def test_unit__derive__top_level_industry_has_no_sub() -> None:
    tax = _mock_tax({"grocery": None})
    top, sub = derive_top_level_and_sub_industry("grocery", tax)
    assert top == "grocery"
    assert sub is None


def test_unit__derive__sub_industry_splits_into_top_plus_sub() -> None:
    tax = _mock_tax({"sportswear": "sports-outdoor", "sports-outdoor": None})
    top, sub = derive_top_level_and_sub_industry("sportswear", tax)
    assert top == "sports-outdoor"
    assert sub == "sportswear"


def test_unit__derive__unknown_industry_falls_back_to_top_level_none_sub() -> None:
    """Hallucinated industry_id from LLM — return it as top-level, sub=None."""
    tax = _mock_tax({})  # not in taxonomy
    top, sub = derive_top_level_and_sub_industry("hallucinated-industry", tax)
    assert top == "hallucinated-industry"
    assert sub is None
