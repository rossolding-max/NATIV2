"""``DiscoveryPrepPackRepository`` — generic CRUD for the discovery_prep_pack model."""

from __future__ import annotations

from app.models.sqla.discovery_prep_pack import DiscoveryPrepPack
from app.repositories.base import BaseRepository


class DiscoveryPrepPackRepository(BaseRepository[DiscoveryPrepPack]):
    model = DiscoveryPrepPack
    pk_attr = "prep_pack_id"
