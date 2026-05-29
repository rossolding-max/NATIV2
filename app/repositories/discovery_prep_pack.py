"""``DiscoveryPrepPackRepository`` — CRUD + versioning queries."""

from __future__ import annotations

from sqlalchemy import false, select, true, update

from app.models.sqla.discovery_prep_pack import DiscoveryPrepPack
from app.repositories.base import BaseRepository


class DiscoveryPrepPackRepository(BaseRepository[DiscoveryPrepPack]):
    """CRUD + per-deal version lookups + ``is_latest`` flip helper."""

    model = DiscoveryPrepPack
    pk_attr = "prep_pack_id"

    async def find_latest_for_deal(self, deal_id: str) -> DiscoveryPrepPack | None:
        """The single row with ``is_latest=true`` for this deal, or None."""
        stmt = (
            select(DiscoveryPrepPack)
            .where(
                self._base_filter(),
                DiscoveryPrepPack.deal_id == deal_id,
                DiscoveryPrepPack.is_latest == true(),
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_all_versions_for_deal(self, deal_id: str) -> list[DiscoveryPrepPack]:
        """All versions for a deal ordered oldest -> newest."""
        stmt = (
            select(DiscoveryPrepPack)
            .where(
                self._base_filter(),
                DiscoveryPrepPack.deal_id == deal_id,
            )
            .order_by(DiscoveryPrepPack.version.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def mark_prior_versions_not_latest(self, deal_id: str) -> int:
        """Flip every ``is_latest=true`` row for this deal to ``false``.

        Must run BEFORE the new row's INSERT (the partial-unique index
        ``ix_prep_pack_latest_per_deal`` enforces at most one latest per deal).
        Returns the count of rows updated.
        """
        stmt = (
            update(DiscoveryPrepPack)
            .where(
                self._base_filter(),
                DiscoveryPrepPack.deal_id == deal_id,
                DiscoveryPrepPack.is_latest == true(),
            )
            .values(is_latest=false())
        )
        result = await self._session.execute(stmt)
        # CursorResult exposes ``rowcount``; the generic ``Result`` does not in
        # pyright's view. Cast at runtime.
        return getattr(result, "rowcount", 0) or 0
