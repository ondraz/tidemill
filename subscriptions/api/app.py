"""FastAPI application with lifespan management."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI

from subscriptions.bus import EventProducer
from subscriptions.database import make_engine, make_session_factory

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db_url = os.environ.get(
        "SUBSCRIPTIONS_DATABASE_URL",
        "postgresql+asyncpg://localhost/subscriptions",
    )
    kafka_url = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

    engine = make_engine(db_url)
    app.state.session_factory = make_session_factory(engine)

    producer = EventProducer(bootstrap_servers=kafka_url)
    await producer.start()
    app.state.producer = producer

    yield

    await producer.stop()
    await engine.dispose()


app = FastAPI(title="Subscriptions API", lifespan=lifespan)

# Register routers
from subscriptions.api.routers import health, metrics, sources, webhooks  # noqa: E402

app.include_router(health.router)
app.include_router(webhooks.router, prefix="/api")
app.include_router(metrics.router, prefix="/api")
app.include_router(sources.router, prefix="/api")
