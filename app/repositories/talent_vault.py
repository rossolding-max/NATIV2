"""``TalentVaultRepository`` — encrypted OAuth tokens per (talent, platform).

The ``access_token`` + ``refresh_token`` columns are ``EncryptedString``
TypeDecorators backed by pgcrypto. SELECT statements transparently decrypt
via ``column_expression``; raw ``select(TalentVault)`` returns plaintext
strings to Python.

Composite PK ``(talent_id, platform)`` means upserts merge on that pair.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sqla.talent_vault import TalentVault


class TalentVaultRepository:
    """Per-(talent, platform) OAuth token CRUD."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        talent_id: str,
        platform: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: datetime | None,
        scopes: list[str],
        scope_validated_at: datetime | None = None,
        agency_id: Any = None,
    ) -> TalentVault:
        """Insert or replace the (talent, platform) row.

        Uses Postgres ``ON CONFLICT DO UPDATE`` so re-running OAuth for the
        same talent overwrites the prior token (refresh-token rotation +
        scope-set updates).

        Uses ``excluded.*`` references in the ``set_`` so the TypeDecorator's
        ``bind_expression`` / ``process_bind_param`` are applied (encrypted
        tokens go through pgcrypto correctly) — passing raw Python values
        in the ``set_`` dict bypasses the type adapter and leaves the prior
        ciphertext untouched.
        """
        insert_stmt = insert(TalentVault).values(
            talent_id=talent_id,
            platform=platform,
            agency_id=agency_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            scopes=scopes,
            scope_validated_at=scope_validated_at,
        )
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[TalentVault.talent_id, TalentVault.platform],
            set_={
                "access_token": insert_stmt.excluded.access_token,
                "refresh_token": insert_stmt.excluded.refresh_token,
                "expires_at": insert_stmt.excluded.expires_at,
                "scopes": insert_stmt.excluded.scopes,
                "scope_validated_at": insert_stmt.excluded.scope_validated_at,
                "agency_id": insert_stmt.excluded.agency_id,
            },
        ).returning(TalentVault)
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.scalar_one()

    async def get(self, *, talent_id: str, platform: str) -> TalentVault | None:
        """Fetch one row by composite key (decrypted by EncryptedString)."""
        stmt = select(TalentVault).where(
            TalentVault.talent_id == talent_id, TalentVault.platform == platform
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_talent(self, talent_id: str) -> list[TalentVault]:
        """All platform credentials for a talent."""
        stmt = select(TalentVault).where(TalentVault.talent_id == talent_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def delete_one(self, *, talent_id: str, platform: str) -> None:
        """Hard-delete one row (used on user-initiated disconnect)."""
        await self._session.execute(
            delete(TalentVault).where(
                TalentVault.talent_id == talent_id, TalentVault.platform == platform
            )
        )
        await self._session.flush()
