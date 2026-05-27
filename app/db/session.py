"""Async SQLAlchemy session factory + FastAPI dependency.

Single source of the engine + sessionmaker. Domain code calls
``Depends(get_db)`` to obtain a session.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings


def create_engine() -> AsyncEngine:
    """Build the async engine from settings. Module-level singleton below."""
    return create_async_engine(
        settings.database_url_async,
        pool_size=settings.postgres_pool_size,
        max_overflow=settings.postgres_max_overflow,
        pool_pre_ping=settings.postgres_pool_pre_ping,
        echo=settings.postgres_echo,
        future=True,
    )


engine: AsyncEngine = create_engine()

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncGenerator[AsyncSession, Any]:
    """FastAPI dependency yielding an async session.

    Commits / rollbacks are the caller's responsibility (service layer
    pattern). The session is closed automatically on exit.
    """
    async with async_session_factory() as session:
        yield session
