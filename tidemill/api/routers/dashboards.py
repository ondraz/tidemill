"""Dashboard and saved-chart CRUD router."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text

from tidemill.api.schemas import (
    DashboardChartAdd,
    DashboardCreate,
    DashboardUpdate,
    SavedChartCreate,
    SavedChartUpdate,
    SectionCreate,
    SectionUpdate,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["dashboards"])


async def _get_session() -> Any:
    from tidemill.api.deps import get_session

    async for s in get_session():
        yield s


async def _get_user_id(request: Request, session: AsyncSession = Depends(_get_session)) -> str:
    """Resolve user id from Clerk JWT or API key."""
    from tidemill.config import AuthConfig

    if not AuthConfig().auth_enabled:
        return "anonymous"

    from tidemill.api.deps import get_current_user

    user = await get_current_user(request)
    if user is None:
        return "anonymous"
    return str(user["id"])


# ── Dashboards ──────────────────────────────────────────────────────────


@router.get("/dashboards")
async def list_dashboards(
    request: Request,
    session: AsyncSession = Depends(_get_session),
) -> list[dict[str, Any]]:
    uid = await _get_user_id(request, session)
    rows = (
        await session.execute(
            text(
                "SELECT id, name, description, created_at, updated_at "
                "FROM dashboard WHERE user_id = :uid ORDER BY updated_at DESC NULLS LAST"
            ),
            {"uid": uid},
        )
    ).all()
    return [
        {
            "id": r[0],
            "name": r[1],
            "description": r[2],
            "created_at": r[3].isoformat() if r[3] else None,
            "updated_at": r[4].isoformat() if r[4] else None,
        }
        for r in rows
    ]


@router.post("/dashboards")
async def create_dashboard(
    body: DashboardCreate,
    request: Request,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    uid = await _get_user_id(request, session)
    did = str(uuid.uuid4())
    now = datetime.now(UTC)
    await session.execute(
        text(
            "INSERT INTO dashboard (id, user_id, name, description, created_at) "
            "VALUES (:id, :uid, :name, :desc, :now)"
        ),
        {"id": did, "uid": uid, "name": body.name, "desc": body.description, "now": now},
    )
    await session.commit()
    return {
        "id": did,
        "name": body.name,
        "description": body.description,
        "created_at": now.isoformat(),
    }


@router.get("/dashboards/{dashboard_id}")
async def get_dashboard(
    dashboard_id: str,
    request: Request,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    uid = await _get_user_id(request, session)
    row = (
        await session.execute(
            text(
                "SELECT id, name, description, created_at, updated_at "
                "FROM dashboard WHERE id = :did AND user_id = :uid"
            ),
            {"did": dashboard_id, "uid": uid},
        )
    ).first()
    if not row:
        raise HTTPException(404, "Dashboard not found")

    # Load sections
    sections_rows = (
        await session.execute(
            text(
                "SELECT id, title, position, created_at "
                "FROM dashboard_section WHERE dashboard_id = :did "
                "ORDER BY position"
            ),
            {"did": dashboard_id},
        )
    ).all()

    sections = []
    for sr in sections_rows:
        # Load charts for this section
        chart_rows = (
            await session.execute(
                text(
                    "SELECT dc.id, dc.saved_chart_id, dc.position, "
                    "sc.name, sc.config "
                    "FROM dashboard_chart dc "
                    "JOIN saved_chart sc ON sc.id = dc.saved_chart_id "
                    "WHERE dc.section_id = :sid ORDER BY dc.position"
                ),
                {"sid": sr[0]},
            )
        ).all()
        charts = [
            {
                "id": cr[0],
                "saved_chart_id": cr[1],
                "position": cr[2],
                "chart": {"name": cr[3], "config": json.loads(cr[4])},
            }
            for cr in chart_rows
        ]
        sections.append({"id": sr[0], "title": sr[1], "position": sr[2], "charts": charts})

    return {
        "id": row[0],
        "name": row[1],
        "description": row[2],
        "created_at": row[3].isoformat() if row[3] else None,
        "updated_at": row[4].isoformat() if row[4] else None,
        "sections": sections,
    }


@router.put("/dashboards/{dashboard_id}")
async def update_dashboard(
    dashboard_id: str,
    body: DashboardUpdate,
    request: Request,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, str]:
    uid = await _get_user_id(request, session)
    sets: list[str] = []
    params: dict[str, Any] = {"did": dashboard_id, "uid": uid, "now": datetime.now(UTC)}
    if body.name is not None:
        sets.append("name = :name")
        params["name"] = body.name
    if body.description is not None:
        sets.append("description = :desc")
        params["desc"] = body.description
    sets.append("updated_at = :now")
    result = await session.execute(
        text(f"UPDATE dashboard SET {', '.join(sets)} WHERE id = :did AND user_id = :uid"),
        params,
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(404, "Dashboard not found")
    await session.commit()
    return {"status": "updated"}


@router.delete("/dashboards/{dashboard_id}")
async def delete_dashboard(
    dashboard_id: str,
    request: Request,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, str]:
    uid = await _get_user_id(request, session)
    result = await session.execute(
        text("DELETE FROM dashboard WHERE id = :did AND user_id = :uid"),
        {"did": dashboard_id, "uid": uid},
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(404, "Dashboard not found")
    await session.commit()
    return {"status": "deleted"}


# ── Sections ────────────────────────────────────────────────────────────


@router.post("/dashboards/{dashboard_id}/sections")
async def create_section(
    dashboard_id: str,
    body: SectionCreate,
    request: Request,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    uid = await _get_user_id(request, session)
    # Verify ownership
    dash = (
        await session.execute(
            text("SELECT id FROM dashboard WHERE id = :did AND user_id = :uid"),
            {"did": dashboard_id, "uid": uid},
        )
    ).first()
    if not dash:
        raise HTTPException(404, "Dashboard not found")

    sid = str(uuid.uuid4())
    now = datetime.now(UTC)
    await session.execute(
        text(
            "INSERT INTO dashboard_section (id, dashboard_id, title, position, created_at) "
            "VALUES (:id, :did, :title, :pos, :now)"
        ),
        {"id": sid, "did": dashboard_id, "title": body.title, "pos": body.position, "now": now},
    )
    await session.execute(
        text("UPDATE dashboard SET updated_at = :now WHERE id = :did"),
        {"now": now, "did": dashboard_id},
    )
    await session.commit()
    return {"id": sid, "title": body.title, "position": body.position}


@router.put("/dashboards/{dashboard_id}/sections/{section_id}")
async def update_section(
    dashboard_id: str,
    section_id: str,
    body: SectionUpdate,
    request: Request,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, str]:
    uid = await _get_user_id(request, session)
    dash = (
        await session.execute(
            text("SELECT id FROM dashboard WHERE id = :did AND user_id = :uid"),
            {"did": dashboard_id, "uid": uid},
        )
    ).first()
    if not dash:
        raise HTTPException(404, "Dashboard not found")

    sets: list[str] = []
    params: dict[str, Any] = {"sid": section_id, "did": dashboard_id}
    if body.title is not None:
        sets.append("title = :title")
        params["title"] = body.title
    if body.position is not None:
        sets.append("position = :pos")
        params["pos"] = body.position
    if not sets:
        return {"status": "no changes"}
    result = await session.execute(
        text(
            f"UPDATE dashboard_section SET {', '.join(sets)} "
            "WHERE id = :sid AND dashboard_id = :did"
        ),
        params,
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(404, "Section not found")
    await session.execute(
        text("UPDATE dashboard SET updated_at = :now WHERE id = :did"),
        {"now": datetime.now(UTC), "did": dashboard_id},
    )
    await session.commit()
    return {"status": "updated"}


@router.delete("/dashboards/{dashboard_id}/sections/{section_id}")
async def delete_section(
    dashboard_id: str,
    section_id: str,
    request: Request,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, str]:
    uid = await _get_user_id(request, session)
    dash = (
        await session.execute(
            text("SELECT id FROM dashboard WHERE id = :did AND user_id = :uid"),
            {"did": dashboard_id, "uid": uid},
        )
    ).first()
    if not dash:
        raise HTTPException(404, "Dashboard not found")
    result = await session.execute(
        text("DELETE FROM dashboard_section WHERE id = :sid AND dashboard_id = :did"),
        {"sid": section_id, "did": dashboard_id},
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(404, "Section not found")
    await session.execute(
        text("UPDATE dashboard SET updated_at = :now WHERE id = :did"),
        {"now": datetime.now(UTC), "did": dashboard_id},
    )
    await session.commit()
    return {"status": "deleted"}


# ── Dashboard Charts (add/remove charts from dashboards) ────────────────


@router.post("/dashboards/{dashboard_id}/charts")
async def add_chart_to_dashboard(
    dashboard_id: str,
    body: DashboardChartAdd,
    request: Request,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    uid = await _get_user_id(request, session)
    dash = (
        await session.execute(
            text("SELECT id FROM dashboard WHERE id = :did AND user_id = :uid"),
            {"did": dashboard_id, "uid": uid},
        )
    ).first()
    if not dash:
        raise HTTPException(404, "Dashboard not found")

    # Verify section belongs to this dashboard
    sec = (
        await session.execute(
            text("SELECT id FROM dashboard_section WHERE id = :sid AND dashboard_id = :did"),
            {"sid": body.section_id, "did": dashboard_id},
        )
    ).first()
    if not sec:
        raise HTTPException(404, "Section not found in this dashboard")

    dcid = str(uuid.uuid4())
    await session.execute(
        text(
            "INSERT INTO dashboard_chart (id, dashboard_id, section_id, saved_chart_id, position) "
            "VALUES (:id, :did, :sid, :cid, :pos)"
        ),
        {
            "id": dcid,
            "did": dashboard_id,
            "sid": body.section_id,
            "cid": body.saved_chart_id,
            "pos": body.position,
        },
    )
    await session.execute(
        text("UPDATE dashboard SET updated_at = :now WHERE id = :did"),
        {"now": datetime.now(UTC), "did": dashboard_id},
    )
    await session.commit()
    return {"id": dcid, "status": "added"}


@router.delete("/dashboards/{dashboard_id}/charts/{chart_id}")
async def remove_chart_from_dashboard(
    dashboard_id: str,
    chart_id: str,
    request: Request,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, str]:
    uid = await _get_user_id(request, session)
    dash = (
        await session.execute(
            text("SELECT id FROM dashboard WHERE id = :did AND user_id = :uid"),
            {"did": dashboard_id, "uid": uid},
        )
    ).first()
    if not dash:
        raise HTTPException(404, "Dashboard not found")
    result = await session.execute(
        text("DELETE FROM dashboard_chart WHERE id = :cid AND dashboard_id = :did"),
        {"cid": chart_id, "did": dashboard_id},
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(404, "Chart not found in dashboard")
    await session.execute(
        text("UPDATE dashboard SET updated_at = :now WHERE id = :did"),
        {"now": datetime.now(UTC), "did": dashboard_id},
    )
    await session.commit()
    return {"status": "removed"}


# ── Saved Charts ────────────────────────────────────────────────────────


@router.get("/charts")
async def list_charts(
    request: Request,
    session: AsyncSession = Depends(_get_session),
) -> list[dict[str, Any]]:
    uid = await _get_user_id(request, session)
    rows = (
        await session.execute(
            text(
                "SELECT id, name, config, created_at, updated_at "
                "FROM saved_chart WHERE user_id = :uid ORDER BY updated_at DESC NULLS LAST"
            ),
            {"uid": uid},
        )
    ).all()
    return [
        {
            "id": r[0],
            "name": r[1],
            "config": json.loads(r[2]),
            "created_at": r[3].isoformat() if r[3] else None,
            "updated_at": r[4].isoformat() if r[4] else None,
        }
        for r in rows
    ]


@router.post("/charts")
async def create_chart(
    body: SavedChartCreate,
    request: Request,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    uid = await _get_user_id(request, session)
    cid = str(uuid.uuid4())
    now = datetime.now(UTC)
    await session.execute(
        text(
            "INSERT INTO saved_chart (id, user_id, name, config, created_at) "
            "VALUES (:id, :uid, :name, :config, :now)"
        ),
        {"id": cid, "uid": uid, "name": body.name, "config": json.dumps(body.config), "now": now},
    )
    await session.commit()
    return {"id": cid, "name": body.name, "config": body.config, "created_at": now.isoformat()}


@router.put("/charts/{chart_id}")
async def update_chart(
    chart_id: str,
    body: SavedChartUpdate,
    request: Request,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, str]:
    uid = await _get_user_id(request, session)
    sets: list[str] = []
    params: dict[str, Any] = {"cid": chart_id, "uid": uid, "now": datetime.now(UTC)}
    if body.name is not None:
        sets.append("name = :name")
        params["name"] = body.name
    if body.config is not None:
        sets.append("config = :config")
        params["config"] = json.dumps(body.config)
    sets.append("updated_at = :now")
    result = await session.execute(
        text(f"UPDATE saved_chart SET {', '.join(sets)} WHERE id = :cid AND user_id = :uid"),
        params,
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(404, "Chart not found")
    await session.commit()
    return {"status": "updated"}


@router.delete("/charts/{chart_id}")
async def delete_chart(
    chart_id: str,
    request: Request,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, str]:
    uid = await _get_user_id(request, session)
    result = await session.execute(
        text("DELETE FROM saved_chart WHERE id = :cid AND user_id = :uid"),
        {"cid": chart_id, "uid": uid},
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(404, "Chart not found")
    await session.commit()
    return {"status": "deleted"}
