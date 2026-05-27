"""``MemoRepository`` — generic CRUD for the memo model."""

from __future__ import annotations

from app.models.sqla.memo import Memo
from app.repositories.base import BaseRepository


class MemoRepository(BaseRepository[Memo]):
    model = Memo
    pk_attr = "memo_id"
