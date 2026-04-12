"""Generic metric endpoints (list + query-by-body)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from tidemill.metrics.base import QuerySpec
from tidemill.metrics.route_helpers import query_metric

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def list_metrics() -> list[str]:
    from tidemill.metrics.registry import discover_metrics

    return sorted(m.name for m in discover_metrics())


@router.get("/metrics/summary")
async def get_summary() -> dict[str, Any]:
    """Return current values for all key metrics in one call."""
    from tidemill.api.app import app
    from tidemill.engine import MetricsEngine

    factory = app.state.session_factory
    async with factory() as session:
        engine = MetricsEngine(db=session)
        result: dict[str, Any] = {}

        queries: dict[str, tuple[str, dict[str, Any]]] = {
            "mrr": ("mrr", {"query_type": "current"}),
            "arr": ("mrr", {"query_type": "arr"}),
            "churn": ("churn", {"query_type": "current"}),
            "retention": ("retention", {"query_type": "current"}),
            "ltv": ("ltv", {"query_type": "current"}),
            "trials": ("trials", {"query_type": "current"}),
        }

        for key, (metric, params) in queries.items():
            try:
                val = await engine.query(metric, params)
                if isinstance(val, dict):
                    result.update(val)
                else:
                    result[key] = val
            except Exception:
                result[key] = None

        return result


@router.post("/metrics/{metric}")
async def post_query_metric(
    metric: str,
    body: dict[str, Any],
) -> Any:
    from tidemill.api.schemas import QuerySpecSchema

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
    return await query_metric(metric, params, spec)
