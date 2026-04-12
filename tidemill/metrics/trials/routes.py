"""Trials metric endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query

from tidemill.metrics.route_helpers import parse_spec, query_metric

router = APIRouter(tags=["metrics"])


@router.get("/metrics/trials")
async def get_trial_conversion(
    start: date = Query(...),
    end: date = Query(...),
    dimensions: list[str] = Query(default=[]),
    filter: list[str] = Query(default=[]),
    granularity: str | None = None,
) -> Any:
    spec = parse_spec(dimensions, filter, granularity)
    return await query_metric(
        "trials", {"query_type": "conversion_rate", "start": start, "end": end}, spec
    )


@router.get("/metrics/trials/series")
async def get_trial_series(
    start: date = Query(...),
    end: date = Query(...),
    interval: str = "month",
    dimensions: list[str] = Query(default=[]),
    filter: list[str] = Query(default=[]),
    granularity: str | None = None,
) -> Any:
    spec = parse_spec(dimensions, filter, granularity)
    return await query_metric(
        "trials",
        {"query_type": "series", "start": start, "end": end, "interval": interval},
        spec,
    )


@router.get("/metrics/trials/funnel")
async def get_trial_funnel(
    start: date = Query(...),
    end: date = Query(...),
    dimensions: list[str] = Query(default=[]),
    filter: list[str] = Query(default=[]),
    granularity: str | None = None,
) -> Any:
    spec = parse_spec(dimensions, filter, granularity)
    return await query_metric("trials", {"query_type": "funnel", "start": start, "end": end}, spec)
