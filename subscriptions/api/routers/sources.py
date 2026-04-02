"""Source management endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks
from sqlalchemy import text

router = APIRouter(tags=["sources"])


@router.get("/sources")
async def list_sources() -> list[dict[str, Any]]:
    from subscriptions.api.app import app

    factory = app.state.session_factory
    async with factory() as session:
        result = await session.execute(
            text("SELECT id, type, name, last_synced_at, created_at FROM connector_source")
        )
        return [dict(r._mapping) for r in result]


@router.post("/sources")
async def create_source(body: dict[str, Any]) -> dict[str, Any]:
    import json

    from subscriptions.api.app import app

    source_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    factory = app.state.session_factory
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO connector_source (id, type, name, config, created_at)"
                " VALUES (:id, :type, :name, :config, :now)"
            ),
            {
                "id": source_id,
                "type": body["type"],
                "name": body.get("name", body["type"]),
                "config": json.dumps(body.get("config", {})),
                "now": now,
            },
        )
        await session.commit()
    return {
        "id": source_id,
        "type": body["type"],
        "name": body.get("name"),
        "created_at": now.isoformat(),
    }


@router.post("/sources/{source_id}/backfill")
async def trigger_backfill(
    source_id: str,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    background_tasks.add_task(_run_backfill, source_id)
    return {"status": "started", "source_id": source_id}


async def _run_backfill(source_id: str) -> None:
    import json

    from subscriptions.api.app import app
    from subscriptions.connectors import get_connector

    factory = app.state.session_factory
    async with factory() as session:
        result = await session.execute(
            text("SELECT type, config FROM connector_source WHERE id = :id"),
            {"id": source_id},
        )
        row = result.fetchone()
        if not row:
            return
        source_type = row[0]
        config = json.loads(row[1]) if row[1] else {}

    connector = get_connector(source_type, source_id=source_id, config=config)
    producer = app.state.producer

    async for event in connector.backfill():
        await producer.publish(event)
