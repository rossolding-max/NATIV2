"""``TalentRepository`` — generic CRUD for the talent model."""

from __future__ import annotations

from app.models.sqla.talent import Talent
from app.repositories.base import BaseRepository


class TalentRepository(BaseRepository[Talent]):
    model = Talent
    pk_attr = "talent_id"
