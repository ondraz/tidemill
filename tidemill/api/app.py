"""FastAPI application with lifespan management."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response

from tidemill._logging import configure_logging
from tidemill.bus import EventProducer
from tidemill.config import AuthConfig
from tidemill.database import make_engine, make_session_factory
from tidemill.otel import init_otel, instrument_fastapi

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# OTEL must be initialized before the FastAPI app is constructed so the
# LoggingInstrumentor log-record factory is in place for startup logs.
init_otel("tidemill-api")
configure_logging("tidemill-api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    import asyncio

    db_url = os.environ.get(
        "TIDEMILL_DATABASE_URL",
        "postgresql+asyncpg://localhost/tidemill",
    )
    kafka_url = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

    engine = make_engine(db_url)

    async with engine.begin() as conn:
        from tidemill.models import metadata as sa_metadata

        await conn.run_sync(sa_metadata.create_all)

        # Ensure the "stripe" connector source exists.
        from sqlalchemy import text

        await conn.execute(
            text(
                "INSERT INTO connector_source (id, type, name, created_at)"
                " VALUES ('stripe', 'stripe', 'Stripe', NOW())"
                " ON CONFLICT (id) DO NOTHING"
            )
        )

    factory = make_session_factory(engine)
    app.state.session_factory = factory

    # Connector configs — used by webhook handlers for signature verification.
    # Per-source config (OAuth tokens, realm IDs) is persisted in
    # ``connector_source.config`` and merged on top at request time.
    app.state.connector_configs = {
        "stripe": {
            "api_key": os.environ.get("STRIPE_API_KEY", ""),
            "webhook_secret": os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
        },
        "quickbooks": {
            "client_id": os.environ.get("QUICKBOOKS_CLIENT_ID", ""),
            "client_secret": os.environ.get("QUICKBOOKS_CLIENT_SECRET", ""),
            "webhook_verifier_token": os.environ.get("QUICKBOOKS_WEBHOOK_VERIFIER_TOKEN", ""),
            "redirect_uri": os.environ.get("QUICKBOOKS_REDIRECT_URI", ""),
            "environment": os.environ.get("QUICKBOOKS_ENVIRONMENT", "production"),
        },
    }

    producer = EventProducer(bootstrap_servers=kafka_url)
    await producer.start()
    app.state.producer = producer

    # Background FX-rate refresher. First tick runs immediately so newly-
    # arrived non-base-currency events have a row to convert against.
    from tidemill.fx_sync import run_periodic_fx_sync

    fx_stop = asyncio.Event()
    fx_task = asyncio.create_task(
        run_periodic_fx_sync(factory, stop=fx_stop),
        name="fx-sync",
    )
    app.state.fx_stop = fx_stop
    app.state.fx_task = fx_task

    yield

    fx_stop.set()
    await asyncio.gather(fx_task, return_exceptions=True)

    await producer.stop()
    await engine.dispose()


app = FastAPI(title="Tidemill API", lifespan=lifespan)
instrument_fastapi(app)

# ── CORS ────────────────────────────────────────────────────────────────

_cfg = AuthConfig()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cfg.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth dependency list (empty when auth is disabled) ──────────────────

from tidemill.api.deps import require_user  # noqa: E402

_auth_deps = [Depends(require_user)] if _cfg.auth_enabled else []

# ── Register routers ────────────────────────────────────────────────────

from tidemill.api.routers import health, metrics, sources, webhooks  # noqa: E402
from tidemill.api.routers.api_keys import router as api_keys_router  # noqa: E402
from tidemill.api.routers.auth import router as auth_router  # noqa: E402
from tidemill.api.routers.dashboards import router as dashboards_router  # noqa: E402

# Public routers
app.include_router(health.router)
app.include_router(auth_router)
app.include_router(webhooks.router, prefix="/api")

# Protected routers
app.include_router(metrics.router, prefix="/api", dependencies=_auth_deps)
app.include_router(sources.router, prefix="/api", dependencies=_auth_deps)
app.include_router(api_keys_router, prefix="/api", dependencies=_auth_deps)
app.include_router(dashboards_router, prefix="/api", dependencies=_auth_deps)

# Segments & attributes
from tidemill.attributes.routes import router as attributes_router  # noqa: E402
from tidemill.segments.routes import router as segments_router  # noqa: E402

app.include_router(segments_router, prefix="/api", dependencies=_auth_deps)
app.include_router(attributes_router, prefix="/api", dependencies=_auth_deps)

# Discover and mount per-metric routers
from tidemill.metrics.registry import discover_metrics  # noqa: E402

for _metric in discover_metrics():
    if _metric.router is not None:
        app.include_router(
            _metric.router,
            prefix="/api",
            tags=[f"metric:{_metric.name}"],
            dependencies=_auth_deps,
        )

# Discover and mount per-connector routers
from tidemill.connectors.registry import get_registry  # noqa: E402

for _conn_cls in get_registry().values():
    _router = _conn_cls.router()
    if _router is not None:
        app.include_router(_router, prefix="/api", dependencies=_auth_deps)


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse("/docs")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    # Wave emoji as SVG favicon
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<text y=".9em" font-size="90">📊</text></svg>'
    )
    return Response(content=svg, media_type="image/svg+xml")
