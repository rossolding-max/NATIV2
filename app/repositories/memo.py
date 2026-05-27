"""``MemoRepository`` — generic CRUD + M2 memo-store extensions.

Adds tag-filter SQL retrieval per the M2 plan:
- ``find_by_tags`` — JSONB tag-filter query (AND across keys, OR within a key
  via the JSONB ``?|`` array-overlap operator).
- ``find_active`` — convenience wrapper using the M1 ``is_active`` hybrid_property.
- ``mark_retrieved`` — atomic UPDATE incrementing ``retrieval_count`` +
  setting ``last_retrieved_at = NOW()``. Called by the ``read_memos`` tool
  AFTER ``find_by_tags`` returns, so ``find_by_tags`` stays side-effect-free
  for tests.

JSONB SQLAlchemy gotcha: the ``?|`` operator uses ``.op("?|")`` form, NOT
``==`` (the ``?`` char collides with parameter placeholders in SQLAlchemy's
SQL compilation).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import Select, and_, or_, select, sql, update

from app.models.sqla.memo import Memo
from app.repositories.base import BaseRepository

SortMode = Literal["recency", "specificity"]


# Scope ordering for "specificity" sort: most specific first.
_SCOPE_RANK: dict[str, int] = {
    "deal_specific": 0,
    "brand_relationship": 1,
    "industry_pattern": 2,
    "talent_pattern": 3,
    "cross_cutting": 4,
}


class MemoRepository(BaseRepository[Memo]):
    model = Memo
    pk_attr = "memo_id"

    # ── M2 extensions ─────────────────────────────────────────────────

    async def find_by_tags(
        self,
        *,
        talent_ids: Iterable[str] | None = None,
        brand_ids: Iterable[str] | None = None,
        industry_ids: Iterable[str] | None = None,
        deal_ids: Iterable[str] | None = None,
        topics: Iterable[str] | None = None,
        scope: Iterable[str] | None = None,
        memo_type: Iterable[str] | None = None,
        limit: int = 20,
        sort: SortMode = "specificity",
        include_expired: bool = False,
        include_deleted: bool = False,
    ) -> list[Memo]:
        """Tag-filter retrieval. Semantics: AND across keys; OR within a key.

        Example: ``find_by_tags(talent_ids=["t1"], topics=["a", "b"])`` returns
        memos where ``tags.talent_ids`` contains ``t1`` AND ``tags.topics`` has
        any element in ``{a, b}``.

        ``sort`` controls ordering — ``specificity`` (default) ranks scopes
        deal_specific > brand_relationship > industry_pattern > talent_pattern
        > cross_cutting, then by ``last_retrieved_at`` DESC, then ``created_at``
        DESC. ``recency`` skips the scope sort and goes straight to dates.
        """
        stmt: Select[tuple[Memo]] = select(Memo).where(self._base_filter())

        # Active filter (unless include_expired or include_deleted overrides).
        if not include_deleted:
            stmt = stmt.where(Memo.is_deleted.is_(False))
        if not include_expired:
            stmt = stmt.where(or_(Memo.expires_at.is_(None), Memo.expires_at > sql.func.now()))

        # JSONB tag filters: OR within each key via the `?|` array-overlap operator.
        tag_filters = []
        for key, values in (
            ("talent_ids", talent_ids),
            ("brand_ids", brand_ids),
            ("industry_ids", industry_ids),
            ("deal_ids", deal_ids),
            ("topics", topics),
        ):
            if values:
                values_list = list(values)
                if not values_list:
                    continue
                # `tags -> 'key'` returns the JSONB sub-value (an array);
                # `?|` tests array-overlap against the given text[].
                tag_filters.append(Memo.tags[key].op("?|")(values_list))
        if tag_filters:
            stmt = stmt.where(and_(*tag_filters))

        # Scalar field filters (multi-value = OR within field via .in_()).
        if scope:
            stmt = stmt.where(Memo.scope.in_(list(scope)))
        if memo_type:
            stmt = stmt.where(Memo.memo_type.in_(list(memo_type)))

        # Sort.
        if sort == "specificity":
            scope_rank = sql.case(_SCOPE_RANK, value=Memo.scope, else_=99)
            stmt = stmt.order_by(
                scope_rank,
                Memo.last_retrieved_at.desc().nulls_last(),
                Memo.created_at.desc(),
            )
        else:
            stmt = stmt.order_by(
                Memo.last_retrieved_at.desc().nulls_last(),
                Memo.created_at.desc(),
            )

        stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def find_active(self, *, limit: int = 20) -> list[Memo]:
        """Convenience: all active (not soft-deleted, not expired) memos for
        the bound agency. Wraps the M1 ``is_active`` hybrid_property.
        """
        stmt = (
            select(Memo)
            .where(self._base_filter(), Memo.is_active)
            .order_by(Memo.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def mark_retrieved(self, memo_ids: Iterable[str]) -> int:
        """Atomic increment of ``retrieval_count`` + set ``last_retrieved_at``.

        Called by the ``read_memos`` tool AFTER ``find_by_tags`` returns the
        filtered memo set. Separating the mutator from the query keeps
        ``find_by_tags`` side-effect-free for tests.

        Returns the count of rows updated.
        """
        ids = list(memo_ids)
        if not ids:
            return 0

        stmt = (
            update(Memo)
            .where(self._base_filter(), Memo.memo_id.in_(ids))
            .values(
                retrieval_count=Memo.retrieval_count + 1,
                last_retrieved_at=datetime.now(UTC),
            )
        )
        result = await self._session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)
