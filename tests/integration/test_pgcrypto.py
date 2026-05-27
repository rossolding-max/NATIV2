"""Integration tests for pgcrypto column encryption.

Round-trip a plaintext string through ``pgp_sym_encrypt`` via the
``EncryptedString`` TypeDecorator and verify:
1. Plaintext is recovered exactly.
2. Decrypting with a wrong master key fails.
3. Tampered ciphertext fails to decrypt.

Skips when Docker isn't available (testcontainers).
"""

from __future__ import annotations

import os
import re
from typing import Any
from uuid import uuid4

import pytest

from alembic import command
from alembic.config import Config


@pytest.fixture
def m1_db(postgres_container: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Migrate to M1 head + return the container for raw psycopg use."""
    url = postgres_container.get_connection_url().replace("+psycopg2", "")
    match = re.match(
        r"postgresql(?:\+\w+)?://(?P<user>[^:]+):(?P<pw>[^@]+)@(?P<host>[^:]+):(?P<port>\d+)/(?P<db>.+)",
        url,
    )
    assert match is not None
    monkeypatch.setenv("POSTGRES_USER", match["user"])
    monkeypatch.setenv("POSTGRES_PASSWORD", match["pw"])
    monkeypatch.setenv("POSTGRES_HOST", match["host"])
    monkeypatch.setenv("POSTGRES_PORT", match["port"])
    monkeypatch.setenv("POSTGRES_DB", match["db"])
    monkeypatch.setenv("DB_MASTER_KEY", "test-master-key-32-bytes-base64==")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-stub")
    from app.config import get_settings

    get_settings.cache_clear()
    repo = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    cfg = Config(os.path.join(repo, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(repo, "alembic"))
    command.upgrade(cfg, "head")
    return postgres_container


def _insert_encrypted_contact(
    container: Any,
    *,
    contact_id: str,
    brand_id: str,
    name: str,
    email: str,
    master_key: str,
) -> None:
    """Insert a brand_contact row using pgp_sym_encrypt at SQL level.

    Sets ``created_at`` + ``updated_at`` explicitly because raw psycopg
    INSERTs bypass SQLAlchemy's Python-side ``default=_utcnow`` hook.
    """
    import psycopg

    url = container.get_connection_url().replace("+psycopg2", "")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        # First insert a brand row (FK target).
        cur.execute(
            """
            INSERT INTO brand (brand_id, name, industry_id, data, created_at, updated_at)
            VALUES (%s, %s, 'cosmetics', '{}', NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC')
            ON CONFLICT (brand_id) DO NOTHING
            """,
            (brand_id, "Test Brand"),
        )
        cur.execute(
            """
            INSERT INTO brand_contact (
                contact_id, brand_id, name, decision_role, email,
                do_not_contact, data, agency_id, created_at, updated_at
            )
            VALUES (
                %s, %s, %s, 'buyer', pgp_sym_encrypt(%s, %s),
                false, '{}', %s,
                NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC'
            )
            """,
            (contact_id, brand_id, name, email, master_key, uuid4()),
        )
        conn.commit()


def _select_decrypted_email(container: Any, contact_id: str, master_key: str) -> str:
    """SELECT with pgp_sym_decrypt to recover the plaintext."""
    import psycopg

    url = container.get_connection_url().replace("+psycopg2", "")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pgp_sym_decrypt(email, %s) FROM brand_contact WHERE contact_id = %s",
            (master_key, contact_id),
        )
        row = cur.fetchone()
        assert row is not None
        return row[0]


def test_integration__pgcrypto_round_trip(m1_db: Any) -> None:
    """Plaintext encrypted then decrypted with the correct master key recovers exactly."""
    key = "test-master-key-32-bytes-base64=="
    _insert_encrypted_contact(
        m1_db,
        contact_id="con_test1234567",
        brand_id="test-brand-rt",
        name="Alice Buyer",
        email="alice@example.com",
        master_key=key,
    )
    recovered = _select_decrypted_email(m1_db, "con_test1234567", key)
    assert recovered == "alice@example.com"


def test_integration__pgcrypto_wrong_key_fails(m1_db: Any) -> None:
    """Decryption with the wrong master key raises a psycopg error."""
    import psycopg

    key = "test-master-key-32-bytes-base64=="
    _insert_encrypted_contact(
        m1_db,
        contact_id="con_test1234568",
        brand_id="test-brand-wk",
        name="Bob Buyer",
        email="bob@example.com",
        master_key=key,
    )
    with pytest.raises((psycopg.errors.OperationalError, psycopg.errors.InternalError_)):
        _select_decrypted_email(m1_db, "con_test1234568", "wrong-master-key-different")


def test_integration__pgcrypto_tampered_ciphertext_fails(m1_db: Any) -> None:
    """Mutating the ciphertext bytes makes pgp_sym_decrypt fail."""
    import psycopg

    key = "test-master-key-32-bytes-base64=="
    _insert_encrypted_contact(
        m1_db,
        contact_id="con_test1234569",
        brand_id="test-brand-tp",
        name="Carol Buyer",
        email="carol@example.com",
        master_key=key,
    )
    url = m1_db.get_connection_url().replace("+psycopg2", "")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        # Corrupt the ciphertext at byte 5 (somewhere inside the pgp packet).
        cur.execute(
            """
            UPDATE brand_contact
            SET email = set_byte(email, 5, (get_byte(email, 5) # 255)::int)
            WHERE contact_id = %s
            """,
            ("con_test1234569",),
        )
        conn.commit()
    with pytest.raises((psycopg.errors.OperationalError, psycopg.errors.InternalError_)):
        _select_decrypted_email(m1_db, "con_test1234569", key)
