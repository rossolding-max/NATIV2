"""``InvoicePackRepository`` — generic CRUD for the invoice_pack model."""

from __future__ import annotations

from app.models.sqla.invoice_pack import InvoicePack
from app.repositories.base import BaseRepository


class InvoicePackRepository(BaseRepository[InvoicePack]):
    model = InvoicePack
    pk_attr = "invoice_pack_id"
