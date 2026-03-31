"""Database connection and session management."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_engine(url: str, **kwargs: Any) -> AsyncEngine:
    """Create an async SQLAlchemy engine.

    *url* should be a PostgreSQL connection string, e.g.
    ``postgresql+asyncpg://user:pass@host/db``.
    """
    return create_async_engine(url, **kwargs)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to *engine*."""
    return async_sessionmaker(engine, expire_on_commit=False)
