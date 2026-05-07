"""/api/segments CRUD + validate."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text

from tidemill.api.schemas import SegmentCreate, SegmentUpdate, SegmentValidate
from tidemill.segments.model import parse_definition, validate_definition

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


router = APIRouter(tags=["segments"])


async def _get_session() -> Any:
    from tidemill.api.deps import get_session

    async for s in get_session():
        yield s


async def _get_user_id(request: Request) -> str | None:
    """Resolve the current user id from Clerk JWT / API key (may be None when auth is off)."""
    from tidemill.config import AuthConfig

    if not AuthConfig().auth_enabled:
        return None
    from tidemill.api.deps import get_current_user

    user = await get_current_user(request)
    return str(user["id"]) if user else None


def _resolve_cube(metric: str) -> Any:
    """Resolve a metric's primary cube via the registry, or raise 4xx.

    The metrics registry is the single source of truth for which cube
    belongs to which metric — each metric advertises its own cube through
    ``Metric.primary_cube``.  This router stays plugin-agnostic.
    Distinguishes 404 (no such metric) from 400 (metric exists but has
    no Cube — e.g. raw-SQL metrics like ``expenses``).
    """
    from tidemill.metrics.registry import metric_exists, metric_primary_cube

    if not metric_exists(metric):
        raise HTTPException(404, f"Unknown metric {metric!r}")
    cube = metric_primary_cube(metric)
    if cube is None:
        raise HTTPException(
            400,
            f"Metric {metric!r} does not support segments (no Cube exposed)",
        )
    return cube


def _row_to_dict(r: Any) -> dict[str, Any]:
    defn = json.loads(r["definition"])
    return {
        "id": r["id"],
        "name": r["name"],
        "description": r["description"],
        "definition": defn,
        "created_by": r["created_by"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
    }


# ── CRUD ────────────────────────────────────────────────────────────────


@router.get("/segments")
async def list_segments(
    session: AsyncSession = Depends(_get_session),
) -> list[dict[str, Any]]:
    """Return every segment (workspace-shared — no per-user filter)."""
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id, name, description, definition, created_by, created_at, updated_at"
                    " FROM segment ORDER BY updated_at DESC NULLS LAST"
                )
            )
        )
        .mappings()
        .all()
    )
    return [_row_to_dict(r) for r in rows]


@router.post("/segments", status_code=201)
async def create_segment(
    body: SegmentCreate,
    request: Request,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    # Parse first — fail fast on malformed definitions.
    try:
        parse_definition(body.definition)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Invalid segment definition: {e}") from e

    uid = await _get_user_id(request)
    sid = str(uuid.uuid4())
    now = datetime.now(UTC)
    await session.execute(
        text(
            "INSERT INTO segment"
            " (id, name, description, definition, created_by, created_at)"
            " VALUES (:id, :name, :desc, :defn, :uid, :now)"
        ),
        {
            "id": sid,
            "name": body.name,
            "desc": body.description,
            "defn": json.dumps(body.definition),
            "uid": uid,
            "now": now,
        },
    )
    await session.commit()
    return {
        "id": sid,
        "name": body.name,
        "description": body.description,
        "definition": body.definition,
        "created_by": uid,
        "created_at": now.isoformat(),
    }


@router.get("/segments/{segment_id}")
async def get_segment(
    segment_id: str,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id, name, description, definition, created_by, created_at, updated_at"
                    " FROM segment WHERE id = :id"
                ),
                {"id": segment_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(404, "Segment not found")
    return _row_to_dict(row)


@router.put("/segments/{segment_id}")
async def update_segment(
    segment_id: str,
    body: SegmentUpdate,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, str]:
    sets: list[str] = []
    params: dict[str, Any] = {"id": segment_id, "now": datetime.now(UTC)}
    if body.name is not None:
        sets.append("name = :name")
        params["name"] = body.name
    if body.description is not None:
        sets.append("description = :desc")
        params["desc"] = body.description
    if body.definition is not None:
        try:
            parse_definition(body.definition)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"Invalid segment definition: {e}") from e
        sets.append("definition = :defn")
        params["defn"] = json.dumps(body.definition)
    if not sets:
        return {"status": "no changes"}
    sets.append("updated_at = :now")
    result = await session.execute(
        text(f"UPDATE segment SET {', '.join(sets)} WHERE id = :id"),
        params,
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(404, "Segment not found")
    await session.commit()
    return {"status": "updated"}


@router.delete("/segments/{segment_id}")
async def delete_segment(
    segment_id: str,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, str]:
    result = await session.execute(
        text("DELETE FROM segment WHERE id = :id"),
        {"id": segment_id},
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(404, "Segment not found")
    await session.commit()
    return {"status": "deleted"}


# ── Validation ──────────────────────────────────────────────────────────


@router.post("/segments/validate")
async def validate_segment(
    body: SegmentValidate,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    """Lint a segment definition without persisting.

    If ``metric`` is supplied, validates against that metric's primary
    cube.  Otherwise validates against every registered metric's primary
    cube and returns per-metric errors.  Used by the FE builder for live
    error display.
    """
    from tidemill.attributes.registry import get_attribute_types

    try:
        defn = parse_definition(body.definition)
    except Exception as e:  # noqa: BLE001
        return {"valid": False, "errors": [f"parse: {e}"]}

    attr_types = await get_attribute_types(session)
    if body.metric is not None:
        cube = _resolve_cube(body.metric)
        errors = validate_definition(defn, cube, attribute_types=attr_types)
        return {"valid": not errors, "errors": errors}

    # No metric — validate against every registered metric's primary cube;
    # a definition is "valid" if it passes at least one cube (the user can
    # still filter by attributes that only resolve on some metrics).
    from tidemill.metrics.registry import registered_names

    by_metric: dict[str, list[str]] = {}
    passed_any = False
    for metric_name in registered_names():
        cube = _resolve_cube(metric_name)
        errors = validate_definition(defn, cube, attribute_types=attr_types)
        by_metric[metric_name] = errors
        if not errors:
            passed_any = True
    return {"valid": passed_any, "errors_by_metric": by_metric}
