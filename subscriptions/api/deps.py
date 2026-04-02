"""FastAPI dependency injection."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

    from subscriptions.bus import EventProducer
    from subscriptions.engine import MetricsEngine


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a database session from the app-scoped factory."""
    from subscriptions.api.app import app

    factory = app.state.session_factory
    async with factory() as session:
        yield session


async def get_engine(
    session: AsyncSession = None,  # type: ignore[assignment]
) -> MetricsEngine:
    from subscriptions.api.app import app
    from subscriptions.engine import MetricsEngine

    factory = app.state.session_factory
    async with factory() as session:
        engine = MetricsEngine(db=session)
        return engine


async def get_producer() -> EventProducer:
    from subscriptions.api.app import app

    producer: EventProducer = app.state.producer
    return producer
