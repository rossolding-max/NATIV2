"""Alembic env — async-aware, online + offline modes.

Online (default): connects via SQLAlchemy 2 async engine.
Offline: emits raw SQL using ``database_url_sync`` (psycopg).

``target_metadata`` is ``Base.metadata`` — the empty baseline at M0; populated
once M1 declares real SQLAlchemy models.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.config import settings
from app.db.base import Base

config = context.config

# Wire stdlib logging from alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode -- emits raw SQL.

    No DB connection; uses the sync DSN so callers can dump SQL even without
    Postgres reachable.
    """
    context.configure(
        url=settings.database_url_sync,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode -- async engine + run_sync()."""
    # Inject the async DSN at runtime (alembic.ini leaves sqlalchemy.url blank).
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = settings.database_url_async

    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
