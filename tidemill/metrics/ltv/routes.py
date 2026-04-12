"""LTV metric endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query

from tidemill.metrics.route_helpers import parse_spec, query_metric

router = APIRouter(tags=["metrics"])


@router.get("/metrics/ltv")
async def get_ltv(
    start: date = Query(...),
    end: date = Query(...),
    at: date | None = None,
    dimensions: list[str] = Query(default=[]),
    filter: list[str] = Query(default=[]),
    granularity: str | None = None,
) -> Any:
    spec = parse_spec(dimensions, filter, granularity)
    return await query_metric(
        "ltv", {"query_type": "simple", "at": at, "start": start, "end": end}, spec
    )


@router.get("/metrics/ltv/arpu")
async def get_arpu(
    at: date | None = None,
    dimensions: list[str] = Query(default=[]),
    filter: list[str] = Query(default=[]),
    granularity: str | None = None,
) -> Any:
    spec = parse_spec(dimensions, filter, granularity)
    return await query_metric("ltv", {"query_type": "arpu", "at": at}, spec)


@router.get("/metrics/ltv/cohort")
async def get_cohort_ltv(
    start: date = Query(...),
    end: date = Query(...),
    dimensions: list[str] = Query(default=[]),
    filter: list[str] = Query(default=[]),
    granularity: str | None = None,
) -> Any:
    spec = parse_spec(dimensions, filter, granularity)
    return await query_metric("ltv", {"query_type": "cohort", "start": start, "end": end}, spec)
