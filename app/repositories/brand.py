"""``BrandRepository`` — global brand catalogue.

Overrides ``_base_filter`` to drop the agency_id constraint (brands are
shared per the M1 plan locked decision). Adds ``create_or_skip`` for the
M1 acceptance import script's insert-only-skip-existing semantics.
"""

from __future__ import annotations

from sqlalchemy import select

from app.errors import BusinessRuleError
from app.models.sqla.brand import Brand
from app.repositories.base import BaseRepository


class BrandRepository(BaseRepository[Brand]):
    model = Brand
    pk_attr = "brand_id"

    async def create_or_skip(self, brand: Brand) -> tuple[Brand, bool]:
        """Insert ``brand`` if no row with the same ``brand_id`` exists.

        Returns ``(brand, created)`` where ``created`` is True if a new row
        was inserted, False if a row already existed (in which case the
        passed-in ``brand`` is discarded and the existing row returned).

        Per the M1 plan: ``import_brand_industry_map.py`` uses this for
        idempotent re-runs. M9 brand-discovery will mutate brand rows
        separately — wholesale upsert here would clobber those changes.
        """
        if not brand.brand_id:
            raise BusinessRuleError("brand_id must be set before create_or_skip")
        existing = await self.get_by_id(brand.brand_id)
        if existing is not None:
            return existing, False
        await self.create(brand)
        return brand, True

    async def list_all(self, *, include_deleted: bool = False) -> list[Brand]:
        """List ALL brands (no pagination). Used by the acceptance test +
        re-export.
        """
        stmt = (
            select(Brand)
            .where(self._base_filter(include_deleted=include_deleted))
            .order_by(Brand.brand_id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
