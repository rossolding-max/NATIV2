"""Database-side encryption via pgcrypto.

Per ``docs/architecture.md`` line 213, sensitive columns (legal names,
emails, phone numbers, contract markdown, etc.) are stored encrypted at
rest using Postgres ``pgp_sym_encrypt(value, master_key)``. The master
key comes from ``settings.db_master_key``.

This module exposes ``EncryptedString``, a SQLAlchemy ``TypeDecorator``
that wraps ``pgp_sym_encrypt`` / ``pgp_sym_decrypt`` SQL functions
transparently — columns annotated ``Mapped[str] = mapped_column(EncryptedString())``
look like normal string columns to the ORM but are encrypted on the wire.

The master key is injected via SQL ``bindparam`` at query construction
time (the chosen approach from the M1 stress-test). We avoid the
``SET LOCAL`` GUC approach because GUCs leak across pooled connections
and are visible in ``pg_stat_activity``.

Usage:

    from sqlalchemy.orm import Mapped, mapped_column
    from app.utils.encryption import EncryptedString

    class Talent(Base):
        legal_name: Mapped[str] = mapped_column(EncryptedString())

Encrypted columns are stored as ``bytea`` in Postgres. The TypeDecorator
handles encoding (Python str → ciphertext bytea on write) and decoding
(bytea → str on read) automatically.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import LargeBinary, func, select
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.types import TypeDecorator

from app.config import settings


class EncryptedString(TypeDecorator[str]):
    """A ``Mapped[str]``-compatible column type encrypted at rest via pgcrypto.

    The plaintext flows through SQL bind parameters (encrypted in transit
    when TLS is enabled). At rest the column holds the ciphertext bytea
    produced by ``pgp_sym_encrypt(value, master_key)``.

    On read, ``pgp_sym_decrypt(value, master_key)`` is applied via a
    column expression rewrite. Callers must use ``select_decrypted()`` or
    one of the repository helpers to get the plaintext back; raw
    ``select(Model)`` returns the bytea (which is intentional — it avoids
    accidentally surfacing plaintext in logs).
    """

    impl = LargeBinary
    cache_ok = True

    @property
    def python_type(self) -> type[str]:
        return str

    def bind_expression(self, bindparam: Any) -> ColumnElement[Any]:
        """Wrap the bound value in ``pgp_sym_encrypt(value, master_key)``."""
        key = settings.db_master_key.get_secret_value()
        return func.pgp_sym_encrypt(bindparam, key)

    def column_expression(self, column: ColumnElement[Any]) -> ColumnElement[Any]:
        """Wrap the column in ``pgp_sym_decrypt(col, master_key)`` on SELECT."""
        key = settings.db_master_key.get_secret_value()
        return func.pgp_sym_decrypt(column, key)


def encrypt_value_sql(value: str) -> ColumnElement[Any]:
    """Standalone helper: return a SQLA expression encrypting ``value``.

    Used for raw inserts and migrations that don't go through the ORM
    layer (e.g. seed-data scripts inserting via ``bulk_insert_mappings``).
    """
    key = settings.db_master_key.get_secret_value()
    return func.pgp_sym_encrypt(value, key)


def decrypt_column_sql(col: ColumnElement[Any]) -> ColumnElement[Any]:
    """Standalone helper: return a SQLA expression decrypting ``col``.

    Used when constructing custom ``select()`` statements that need the
    plaintext, e.g. ``select(decrypt_column_sql(Talent.legal_name))``.
    """
    key = settings.db_master_key.get_secret_value()
    return func.pgp_sym_decrypt(col, key)


__all__ = [
    "EncryptedString",
    "decrypt_column_sql",
    "encrypt_value_sql",
    "select",  # re-exported for convenience
]
