"""``ProposalPackRepository`` — generic CRUD for the proposal_pack model."""

from __future__ import annotations

from app.models.sqla.proposal_pack import ProposalPack
from app.repositories.base import BaseRepository


class ProposalPackRepository(BaseRepository[ProposalPack]):
    model = ProposalPack
    pk_attr = "proposal_pack_id"
