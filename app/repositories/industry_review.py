"""``IndustryReviewRepository`` — Phase 1.5 review queue CRUD (M7.7).

Manages one pending IndustryReview per (talent, agency). When
``create_pending`` is called with an existing pending record, the older
record is soft-deleted (status set to 'rejected', is_deleted=True) so
only the latest proposal survives.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import BusinessRuleError, NotFoundError
from app.models.sqla.industry_review import IndustryReview
from app.repositories.base import BaseRepository


class IndustryReviewRepository(BaseRepository[IndustryReview]):
    """CRUD for the M7.7 Phase 1.5 review queue."""

    model = IndustryReview
    pk_attr = "review_id"

    def __init__(self, session: AsyncSession, agency_id: UUID | None = None) -> None:
        super().__init__(session, agency_id or UUID(int=0))

    async def create_pending(
        self,
        *,
        talent_id: str,
        items: list[dict[str, Any]],
        search_run_id: str | None = None,
    ) -> IndustryReview:
        """Create a new pending review for the talent.

        If a pending review already exists, soft-rejects the previous one
        so only the latest proposal is active. Returns the new record.
        """
        # Reject any prior pending so a fresh full_build doesn't pile up.
        prior = await self.get_pending(talent_id)
        if prior is not None:
            prior.status = "rejected"
            prior.is_deleted = True
            prior.deleted_at = datetime.now(UTC)
            await self._session.flush()

        review = IndustryReview(
            review_id=f"ir_{uuid4().hex[:24]}",
            talent_id=talent_id,
            status="pending",
            items=items,
            search_run_id=search_run_id,
        )
        review.agency_id = self._agency_id
        await self.create(review)
        return review

    async def get_pending(self, talent_id: str) -> IndustryReview | None:
        """Return the most-recent pending review for the talent (or None)."""
        stmt = (
            select(IndustryReview)
            .where(
                self._base_filter(),
                IndustryReview.talent_id == talent_id,
                IndustryReview.status == "pending",
            )
            .order_by(desc(IndustryReview.created_at))
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(  # type: ignore[override]
        self, review_id: str
    ) -> IndustryReview | None:
        stmt = select(IndustryReview).where(
            self._base_filter(),
            IndustryReview.review_id == review_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def patch_items(
        self,
        review_id: str,
        *,
        added: list[dict[str, Any]] | None = None,
        removed: list[str] | None = None,
    ) -> IndustryReview:
        """Toggle approval per industry_id.

        - ``removed``: industry_ids whose ``approved`` flag flips to False.
        - ``added``: list of new entries (full IndustryReviewItem dicts) to
          append. Each gets ``source="manual"`` enforced.

        Only callable on pending records — approved records are immutable.
        """
        review = await self.get_by_id(review_id)
        if review is None:
            raise NotFoundError(
                f"industry_review {review_id!r} not found", detail={"review_id": review_id}
            )
        if review.status != "pending":
            raise BusinessRuleError(
                f"industry_review {review_id!r} is {review.status!r}, not pending",
                detail={"review_id": review_id, "status": review.status},
            )

        items: list[dict[str, Any]] = list(review.items or [])

        if removed:
            removed_set = {r.strip().lower() for r in removed if r}
            for entry in items:
                if (entry.get("industry_id") or "").strip().lower() in removed_set:
                    entry["approved"] = False

        if added:
            existing_ids = {(e.get("industry_id") or "").strip().lower() for e in items}
            for new in added:
                if not new:
                    continue
                iid = (new.get("industry_id") or "").strip()
                if not iid or iid.lower() in existing_ids:
                    continue
                items.append(
                    {
                        "industry_id": iid,
                        "rationale": str(
                            new.get("rationale") or "Manually added by agency operator"
                        ),
                        "source": "manual",
                        "approved": True,
                        "alternate_rationales": [],
                    }
                )
                existing_ids.add(iid.lower())

        review.items = items
        await self._session.flush()
        await self._session.refresh(review)
        return review

    async def mark_approved(self, review_id: str) -> IndustryReview:
        """Mark a pending review approved. Immutable after this call."""
        review = await self.get_by_id(review_id)
        if review is None:
            raise NotFoundError(
                f"industry_review {review_id!r} not found", detail={"review_id": review_id}
            )
        if review.status != "pending":
            raise BusinessRuleError(
                f"industry_review {review_id!r} is {review.status!r}, not pending",
                detail={"review_id": review_id, "status": review.status},
            )
        review.status = "approved"
        review.approved_at = datetime.now(UTC)
        await self._session.flush()
        await self._session.refresh(review)
        return review
