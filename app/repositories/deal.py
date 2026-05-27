"""``DealRepository`` — generic CRUD for the deal model."""

from __future__ import annotations

from app.models.sqla.deal import Deal
from app.repositories.base import BaseRepository


class DealRepository(BaseRepository[Deal]):
    model = Deal
    pk_attr = "deal_id"
