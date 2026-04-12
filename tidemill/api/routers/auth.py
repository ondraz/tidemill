"""Clerk-based authentication router.

Clerk handles user sign-in/sign-up entirely on the frontend.  The backend
verifies Clerk session JWTs sent in the ``Authorization: Bearer <token>``
header.  A local ``app_user`` row is upserted on first API call so that
dashboards, charts, and API keys have a stable owner reference.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text

from tidemill.config import AuthConfig

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["auth"])

_cfg = AuthConfig()

# Clerk JWKS is cached in-process.
_jwks_client: jwt.PyJWKClient | None = None


def _get_jwks_client() -> jwt.PyJWKClient:
    global _jwks_client  # noqa: PLW0603
    if _jwks_client is None:
        jwks_url = _cfg.clerk_jwks_url
        if not jwks_url and _cfg.clerk_secret_key:
            # Derive JWKS URL from the Clerk secret key's instance ID.
            # Secret key format: sk_test_<key> or sk_live_<key>
            # We fetch from Clerk's frontend API JWKS endpoint.
            # Users can also set CLERK_JWKS_URL explicitly.
            jwks_url = ""
        if not jwks_url:
            raise HTTPException(500, "CLERK_JWKS_URL is not configured")
        _jwks_client = jwt.PyJWKClient(jwks_url)
    return _jwks_client


async def _get_session() -> Any:
    from tidemill.api.deps import get_session

    async for s in get_session():
        yield s


def verify_clerk_token(request: Request) -> dict[str, Any]:
    """Extract and verify a Clerk JWT from the Authorization header."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer ") or auth_header.startswith("Bearer tk_"):
        raise HTTPException(401, "Missing or invalid Clerk token")

    token = auth_header[7:]
    try:
        client = _get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
        return payload  # type: ignore[no-any-return]
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(401, "Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(401, f"Invalid token: {exc}") from exc


async def upsert_user(
    clerk_user_id: str,
    session: AsyncSession,
    *,
    email: str | None = None,
    name: str | None = None,
    avatar_url: str | None = None,
) -> str:
    """Ensure a local app_user row exists for this Clerk user."""
    now = datetime.now(UTC)
    row = (
        await session.execute(
            text("SELECT id FROM app_user WHERE id = :uid"),
            {"uid": clerk_user_id},
        )
    ).first()
    if row:
        await session.execute(
            text("UPDATE app_user SET last_seen_at = :now WHERE id = :uid"),
            {"now": now, "uid": clerk_user_id},
        )
    else:
        await session.execute(
            text(
                "INSERT INTO app_user (id, email, name, avatar_url, created_at, last_seen_at) "
                "VALUES (:uid, :email, :name, :avatar, :now, :now)"
            ),
            {
                "uid": clerk_user_id,
                "email": email,
                "name": name,
                "avatar": avatar_url,
                "now": now,
            },
        )
    await session.commit()
    return clerk_user_id


# ── Endpoints ────────────────────────────────────────────────────────────


@router.get("/auth/me")
async def me(
    request: Request,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    """Return the current user.  Verifies Clerk JWT and upserts local user."""
    cfg = AuthConfig()
    if not cfg.auth_enabled:
        return {"id": "anonymous", "email": None, "name": None, "avatar_url": None}

    claims = verify_clerk_token(request)
    clerk_id: str = claims["sub"]

    await upsert_user(clerk_id, session)

    row = (
        await session.execute(
            text("SELECT id, email, name, avatar_url FROM app_user WHERE id = :uid"),
            {"uid": clerk_id},
        )
    ).first()
    if not row:
        raise HTTPException(500, "User upsert failed")
    return {"id": row[0], "email": row[1], "name": row[2], "avatar_url": row[3]}


@router.get("/auth/config")
async def auth_config() -> dict[str, Any]:
    """Return public auth configuration for the frontend."""
    cfg = AuthConfig()
    return {
        "auth_enabled": cfg.auth_enabled,
        "clerk_publishable_key": cfg.clerk_publishable_key if cfg.auth_enabled else None,
    }
