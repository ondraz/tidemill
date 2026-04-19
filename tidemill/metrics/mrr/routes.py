"""MRR metric endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query

from tidemill.metrics.route_helpers import parse_spec, query_metric

router = APIRouter(tags=["metrics"])


@router.get("/metrics/mrr")
async def get_mrr(
    at: date | None = None,
    start: date | None = None,
    end: date | None = None,
    interval: str = "month",
    dimensions: list[str] = Query(default=[]),
    filter: list[str] = Query(default=[]),
    granularity: str | None = None,
) -> Any:
    spec = parse_spec(dimensions, filter, granularity)
    if start and end:
        params = {"query_type": "series", "start": start, "end": end, "interval": interval}
    else:
        params = {"query_type": "current", "at": at}
    return await query_metric("mrr", params, spec)


@router.get("/metrics/mrr/breakdown")
async def get_mrr_breakdown(
    start: date = Query(...),
    end: date = Query(...),
    dimensions: list[str] = Query(default=[]),
    filter: list[str] = Query(default=[]),
    granularity: str | None = None,
) -> Any:
    spec = parse_spec(dimensions, filter, granularity)
    return await query_metric("mrr", {"query_type": "breakdown", "start": start, "end": end}, spec)


@router.get("/metrics/mrr/waterfall")
async def get_mrr_waterfall(
    start: date = Query(...),
    end: date = Query(...),
    interval: str = "month",
    dimensions: list[str] = Query(default=[]),
    filter: list[str] = Query(default=[]),
    granularity: str | None = None,
) -> Any:
    spec = parse_spec(dimensions, filter, granularity)
    return await query_metric(
        "mrr",
        {"query_type": "waterfall", "start": start, "end": end, "interval": interval},
        spec,
    )


@router.get("/metrics/arr")
async def get_arr(
    at: date | None = None,
    dimensions: list[str] = Query(default=[]),
    filter: list[str] = Query(default=[]),
    granularity: str | None = None,
) -> Any:
    spec = parse_spec(dimensions, filter, granularity)
    return await query_metric("mrr", {"query_type": "arr", "at": at}, spec)
