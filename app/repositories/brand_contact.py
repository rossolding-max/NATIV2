"""``BrandContactRepository`` — generic CRUD for the brand_contact model."""

from __future__ import annotations

from app.models.sqla.brand_contact import BrandContact
from app.repositories.base import BaseRepository


class BrandContactRepository(BaseRepository[BrandContact]):
    model = BrandContact
    pk_attr = "contact_id"
