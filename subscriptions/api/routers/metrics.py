"""Metric query endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Query

from subscriptions.metrics.base import QuerySpec

if TYPE_CHECKING:
    from datetime import date

router = APIRouter(tags=["metrics"])


def _parse_spec(
    dimensions: list[str] = Query(default=[]),
    filter: list[str] = Query(default=[]),
    granularity: str | None = None,
) -> QuerySpec | None:
    filters: dict[str, Any] = {}
    for f in filter:
        key, _, value = f.partition("=")
        filters[key] = value
    if not dimensions and not filters and not granularity:
        return None
    return QuerySpec(dimensions=dimensions, filters=filters, granularity=granularity)


async def _query(metric: str, params: dict[str, Any], spec: QuerySpec | None) -> Any:
    from subscriptions.api.app import app
    from subscriptions.engine import MetricsEngine

    factory = app.state.session_factory
    async with factory() as session:
        engine = MetricsEngine(db=session)
        return await engine.query(metric, params, spec)


@router.get("/metrics")
async def list_metrics() -> list[str]:
    from subscriptions.metrics.registry import discover_metrics

    return sorted(m.name for m in discover_metrics())


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
    spec = _parse_spec(dimensions, filter, granularity)
    if start and end:
        params = {"query_type": "series", "start": start, "end": end, "interval": interval}
    else:
        params = {"query_type": "current", "at": at}
    return await _query("mrr", params, spec)


@router.get("/metrics/mrr/breakdown")
async def get_mrr_breakdown(
    start: date = Query(...),
    end: date = Query(...),
    dimensions: list[str] = Query(default=[]),
    filter: list[str] = Query(default=[]),
    granularity: str | None = None,
) -> Any:
    spec = _parse_spec(dimensions, filter, granularity)
    return await _query("mrr", {"query_type": "breakdown", "start": start, "end": end}, spec)


@router.get("/metrics/arr")
async def get_arr(
    at: date | None = None,
    dimensions: list[str] = Query(default=[]),
    filter: list[str] = Query(default=[]),
    granularity: str | None = None,
) -> Any:
    spec = _parse_spec(dimensions, filter, granularity)
    return await _query("mrr", {"query_type": "arr", "at": at}, spec)


@router.get("/metrics/churn")
async def get_churn(
    start: date = Query(...),
    end: date = Query(...),
    type: str = "logo",
    dimensions: list[str] = Query(default=[]),
    filter: list[str] = Query(default=[]),
    granularity: str | None = None,
) -> Any:
    spec = _parse_spec(dimensions, filter, granularity)
    return await _query("churn", {"start": start, "end": end, "type": type}, spec)


@router.get("/metrics/retention")
async def get_retention(
    start: date = Query(...),
    end: date = Query(...),
    query_type: str = "cohort_matrix",
    dimensions: list[str] = Query(default=[]),
    filter: list[str] = Query(default=[]),
    granularity: str | None = None,
) -> Any:
    spec = _parse_spec(dimensions, filter, granularity)
    return await _query("retention", {"query_type": query_type, "start": start, "end": end}, spec)


@router.post("/metrics/{metric}")
async def query_metric(
    metric: str,
    body: dict[str, Any],
) -> Any:
    from subscriptions.api.schemas import QuerySpecSchema

    params = body.get("params", {})
    raw_spec = body.get("spec")
    spec = None
    if raw_spec:
        s = QuerySpecSchema(**raw_spec)
        spec = QuerySpec(
            dimensions=s.dimensions,
            filters=s.filters,
            granularity=s.granularity,
        )
    return await _query(metric, params, spec)
