"""``ContractPackRepository`` — generic CRUD for the contract_pack model."""

from __future__ import annotations

from app.models.sqla.contract_pack import ContractPack
from app.repositories.base import BaseRepository


class ContractPackRepository(BaseRepository[ContractPack]):
    model = ContractPack
    pk_attr = "contract_pack_id"
