"""Churn metric endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query

from tidemill.metrics.route_helpers import parse_spec, query_metric

router = APIRouter(tags=["metrics"])


@router.get("/metrics/churn")
async def get_churn(
    start: date = Query(...),
    end: date = Query(...),
    type: str = "logo",
    dimensions: list[str] = Query(default=[]),
    filter: list[str] = Query(default=[]),
    granularity: str | None = None,
) -> Any:
    spec = parse_spec(dimensions, filter, granularity)
    return await query_metric("churn", {"start": start, "end": end, "type": type}, spec)


@router.get("/metrics/churn/customers")
async def get_churn_customers(
    start: date = Query(...),
    end: date = Query(...),
) -> Any:
    return await query_metric("churn", {"start": start, "end": end, "type": "detail"}, None)


@router.get("/metrics/churn/revenue-events")
async def get_churn_revenue_events(
    start: date = Query(...),
    end: date = Query(...),
) -> Any:
    return await query_metric(
        "churn", {"start": start, "end": end, "type": "revenue_events"}, None
    )
