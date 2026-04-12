"""API key management router."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["api-keys"])


async def _get_session() -> Any:
    from tidemill.api.deps import get_session

    async for s in get_session():
        yield s


async def _require_clerk_user(
    request: Request, session: AsyncSession = Depends(_get_session)
) -> str:
    """Require Clerk JWT auth (not API key) for key management.

    API key management must use Clerk auth to prevent a compromised key
    from creating more keys.
    """
    from tidemill.api.routers.auth import upsert_user, verify_clerk_token
    from tidemill.config import AuthConfig

    if not AuthConfig().auth_enabled:
        return "anonymous"

    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer tk_"):
        raise HTTPException(403, "API key management requires Clerk authentication, not API key")

    claims = verify_clerk_token(request)
    clerk_id: str = claims["sub"]
    await upsert_user(clerk_id, session)
    return clerk_id


@router.get("/keys")
async def list_keys(
    user_id: str = Depends(_require_clerk_user),
    session: AsyncSession = Depends(_get_session),
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT id, name, key_prefix, created_at, last_used_at, revoked_at "
                "FROM api_key WHERE user_id = :uid ORDER BY created_at DESC"
            ),
            {"uid": user_id},
        )
    ).all()
    return [
        {
            "id": r[0],
            "name": r[1],
            "key_prefix": r[2],
            "created_at": r[3].isoformat() if r[3] else None,
            "last_used_at": r[4].isoformat() if r[4] else None,
            "revoked_at": r[5].isoformat() if r[5] else None,
        }
        for r in rows
    ]


@router.post("/keys")
async def create_key(
    body: dict[str, str],
    user_id: str = Depends(_require_clerk_user),
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "Name is required")

    raw_key = "tk_" + secrets.token_hex(16)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:11]  # "tk_" + 8 hex chars
    key_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    await session.execute(
        text(
            "INSERT INTO api_key (id, user_id, name, key_hash, key_prefix, created_at) "
            "VALUES (:id, :uid, :name, :hash, :prefix, :now)"
        ),
        {
            "id": key_id,
            "uid": user_id,
            "name": name,
            "hash": key_hash,
            "prefix": key_prefix,
            "now": now,
        },
    )
    await session.commit()

    return {
        "id": key_id,
        "name": name,
        "key_prefix": key_prefix,
        "key": raw_key,
        "created_at": now.isoformat(),
    }


@router.delete("/keys/{key_id}")
async def revoke_key(
    key_id: str,
    user_id: str = Depends(_require_clerk_user),
    session: AsyncSession = Depends(_get_session),
) -> dict[str, str]:
    result = await session.execute(
        text(
            "UPDATE api_key SET revoked_at = :now "
            "WHERE id = :kid AND user_id = :uid AND revoked_at IS NULL"
        ),
        {"now": datetime.now(UTC), "kid": key_id, "uid": user_id},
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(404, "API key not found")
    await session.commit()
    return {"status": "revoked"}
