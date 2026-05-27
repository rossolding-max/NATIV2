"""``BrandDealRepository`` — generic CRUD for the brand_deal model."""

from __future__ import annotations

from app.models.sqla.brand_deal import BrandDeal
from app.repositories.base import BaseRepository


class BrandDealRepository(BaseRepository[BrandDeal]):
    model = BrandDeal
    pk_attr = "brand_deal_id"
