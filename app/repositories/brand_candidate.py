"""``BrandCandidateRepository`` — generic CRUD for the brand_candidate model."""

from __future__ import annotations

from app.models.sqla.brand_candidate import BrandCandidate
from app.repositories.base import BaseRepository


class BrandCandidateRepository(BaseRepository[BrandCandidate]):
    model = BrandCandidate
    pk_attr = "candidate_id"
