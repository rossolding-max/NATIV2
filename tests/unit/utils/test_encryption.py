"""Unit tests for ``app.utils.encryption.EncryptedString``.

These tests verify the Python-side machinery (TypeDecorator wiring,
SQL expression generation, helper functions). The actual round-trip
through a Postgres ``pgp_sym_encrypt`` is covered by
``tests/integration/test_pgcrypto.py``.
"""

from __future__ import annotations

from sqlalchemy import LargeBinary, func
from sqlalchemy.dialects.postgresql import dialect as pg_dialect

from app.utils.encryption import EncryptedString, decrypt_column_sql, encrypt_value_sql


def test_unit__encrypted_string_impl_is_large_binary() -> None:
    """``EncryptedString`` stores as ``bytea`` (Postgres LargeBinary)."""
    e = EncryptedString()
    assert isinstance(e.impl_instance, LargeBinary)
    assert e.cache_ok is True


def test_unit__encrypted_string_python_type_is_str() -> None:
    """``EncryptedString`` exposes a Python ``str`` interface."""
    assert EncryptedString().python_type is str


def test_unit__bind_expression_wraps_in_pgp_sym_encrypt() -> None:
    """``bind_expression`` produces a ``pgp_sym_encrypt(:val, key)`` SQL call."""
    e = EncryptedString()
    expr = e.bind_expression(func.bindparam("val"))
    rendered = str(expr.compile(dialect=pg_dialect()))
    assert "pgp_sym_encrypt" in rendered


def test_unit__column_expression_wraps_in_pgp_sym_decrypt() -> None:
    """``column_expression`` produces a ``pgp_sym_decrypt(col, key)`` SQL call."""
    e = EncryptedString()
    col = func.bindparam("col")
    expr = e.column_expression(col)
    rendered = str(expr.compile(dialect=pg_dialect()))
    assert "pgp_sym_decrypt" in rendered


def test_unit__encrypt_value_sql_helper() -> None:
    """``encrypt_value_sql`` returns a SQL expression for raw inserts."""
    expr = encrypt_value_sql("hello")
    rendered = str(expr.compile(dialect=pg_dialect(), compile_kwargs={"literal_binds": True}))
    assert "pgp_sym_encrypt" in rendered
    assert "hello" in rendered


def test_unit__decrypt_column_sql_helper() -> None:
    """``decrypt_column_sql`` returns a SQL expression for custom selects."""
    col = func.bindparam("encrypted_col")
    expr = decrypt_column_sql(col)
    rendered = str(expr.compile(dialect=pg_dialect()))
    assert "pgp_sym_decrypt" in rendered
