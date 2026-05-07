"""MRR metric endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends

from tidemill.metrics.base import QuerySpec
from tidemill.metrics.route_helpers import parse_spec, query_metric

router = APIRouter(tags=["metrics"])


@router.get("/metrics/mrr")
async def get_mrr(
    at: date | None = None,
    start: date | None = None,
    end: date | None = None,
    interval: str = "month",
    spec: QuerySpec | None = Depends(parse_spec),
) -> Any:
    if start and end:
        params = {"query_type": "series", "start": start, "end": end, "interval": interval}
    else:
        params = {"query_type": "current", "at": at}
    return await query_metric("mrr", params, spec)


@router.get("/metrics/mrr/components")
async def get_mrr_components(
    spec: QuerySpec | None = Depends(parse_spec),
) -> Any:
    """Current MRR split into ``subscription_mrr`` + ``usage_mrr`` (cents)."""
    return await query_metric("mrr", {"query_type": "components"}, spec)


@router.get("/metrics/mrr/breakdown")
async def get_mrr_breakdown(
    start: date,
    end: date,
    spec: QuerySpec | None = Depends(parse_spec),
) -> Any:
    return await query_metric("mrr", {"query_type": "breakdown", "start": start, "end": end}, spec)


@router.get("/metrics/mrr/waterfall")
async def get_mrr_waterfall(
    start: date,
    end: date,
    interval: str = "month",
    spec: QuerySpec | None = Depends(parse_spec),
) -> Any:
    return await query_metric(
        "mrr",
        {"query_type": "waterfall", "start": start, "end": end, "interval": interval},
        spec,
    )


@router.get("/metrics/arr")
async def get_arr(
    at: date | None = None,
    start: date | None = None,
    end: date | None = None,
    interval: str = "month",
    spec: QuerySpec | None = Depends(parse_spec),
) -> Any:
    if start and end:
        params = {"query_type": "arr", "start": start, "end": end, "interval": interval}
    else:
        params = {"query_type": "arr", "at": at}
    return await query_metric("mrr", params, spec)
