"""FastAPI dependency injection."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, Request
from sqlalchemy import text

from tidemill.config import AuthConfig

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

    from tidemill.bus import EventProducer
    from tidemill.engine import MetricsEngine


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a database session from the app-scoped factory."""
    from tidemill.api.app import app

    factory = app.state.session_factory
    async with factory() as session:
        yield session


async def get_engine(
    session: AsyncSession = None,  # type: ignore[assignment]
) -> MetricsEngine:
    from tidemill.api.app import app
    from tidemill.engine import MetricsEngine

    factory = app.state.session_factory
    async with factory() as session:
        engine = MetricsEngine(db=session)
        return engine


async def get_producer() -> EventProducer:
    from tidemill.api.app import app

    producer: EventProducer = app.state.producer
    return producer


async def get_current_user(request: Request) -> dict[str, Any] | None:
    """Resolve current user from Clerk JWT or API key.

    Returns a dict with user data, or ``None`` when auth is disabled.
    Raises 401 when auth is enabled but no valid credentials are found.
    """
    cfg = AuthConfig()
    if not cfg.auth_enabled:
        return None

    from tidemill.api.app import app

    factory = app.state.session_factory
    async with factory() as session:
        # Try API key first (tk_ prefix)
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer tk_"):
            user = await _resolve_api_key(auth_header[7:], session)
            if user is not None:
                return user

        # Try Clerk JWT
        if auth_header.startswith("Bearer ") and not auth_header.startswith("Bearer tk_"):
            from tidemill.api.routers.auth import upsert_user, verify_clerk_token

            try:
                claims = verify_clerk_token(request)
            except HTTPException:
                raise
            clerk_id: str = claims["sub"]
            await upsert_user(clerk_id, session)
            row = (
                await session.execute(
                    text("SELECT id, email, name, avatar_url FROM app_user WHERE id = :uid"),
                    {"uid": clerk_id},
                )
            ).first()
            if row:
                return {"id": row[0], "email": row[1], "name": row[2], "avatar_url": row[3]}

    raise HTTPException(status_code=401, detail="Authentication required")


async def require_user(request: Request) -> dict[str, Any] | None:
    """Dependency that enforces auth when enabled."""
    return await get_current_user(request)


async def _resolve_api_key(raw_key: str, session: AsyncSession) -> dict[str, Any] | None:
    """Look up an API key by its SHA-256 hash."""
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    row = (
        await session.execute(
            text(
                "SELECT u.id, u.email, u.name, u.avatar_url "
                "FROM api_key k JOIN app_user u ON u.id = k.user_id "
                "WHERE k.key_hash = :hash AND k.revoked_at IS NULL"
            ),
            {"hash": key_hash},
        )
    ).first()
    if row:
        await session.execute(
            text("UPDATE api_key SET last_used_at = :now WHERE key_hash = :hash"),
            {"now": datetime.now(UTC), "hash": key_hash},
        )
        await session.commit()
        return {"id": row[0], "email": row[1], "name": row[2], "avatar_url": row[3]}
    return None
