"""``AgencyProfileRepository`` — generic CRUD for the agency_profile model."""

from __future__ import annotations

from app.models.sqla.agency_profile import AgencyProfile
from app.repositories.base import BaseRepository


class AgencyProfileRepository(BaseRepository[AgencyProfile]):
    model = AgencyProfile
    pk_attr = "agency_id"
