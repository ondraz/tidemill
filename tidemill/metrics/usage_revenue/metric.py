"""UsageRevenueMetric — actuals view over finalized monthly metered charges.

This metric does not consume events. The canonical store
(``metric_mrr_usage_component``) is populated by the MRR metric's
``invoice.paid`` handler in :mod:`tidemill.metrics.mrr.usage`. Usage revenue
exists so callers can read raw per-month actuals without going through the
trailing-3m smoothing applied to MRR.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tidemill.metrics.base import Metric, QuerySpec
from tidemill.metrics.registry import register
from tidemill.metrics.usage_revenue.cubes import UsageRevenueCube
from tidemill.segments.compiler import build_spec_fragment

if TYPE_CHECKING:
    from datetime import date

    from fastapi import APIRouter


@register
class UsageRevenueMetric(Metric):
    name = "usage_revenue"
    model = UsageRevenueCube

    @property
    def router(self) -> APIRouter:
        from tidemill.metrics.usage_revenue.routes import router

        return router

    @property
    def dependencies(self) -> list[str]:
        # MRR owns the underlying table and must be initialized first so its
        # invoice.paid handler is wired before any usage_revenue query runs.
        return ["mrr"]

    @property
    def event_types(self) -> list[str]:
        return []

    async def query(self, params: dict[str, Any], spec: QuerySpec | None = None) -> Any:
        match params.get("query_type"):
            case "total":
                return await self._total(params["start"], params["end"], spec)
            case "series":
                return await self._series(
                    params["start"],
                    params["end"],
                    params.get("interval", "month"),
                    spec,
                )
            case "by_customer":
                return await self._by_customer(params["start"], params["end"], spec)
            case other:
                raise ValueError(f"Unknown query_type: {other}")

    async def _total(
        self,
        start: date,
        end: date,
        spec: QuerySpec | None,
    ) -> Any:
        m = self.model
        use_original = spec and "currency" in (spec.dimensions or [])
        measure = m.measures.revenue_original if use_original else m.measures.revenue
        q = measure + m.filter("period_start", "between", (start, end))
        q = q + await build_spec_fragment(m, spec, self.db)
        stmt, params = q.compile(m)
        result = await self.db.execute(stmt, params)
        rows = result.mappings().all()
        if not spec or (not spec.dimensions and not (spec and spec.compare)):
            return float(rows[0]["revenue"] or 0) if rows else 0
        return [dict(r) for r in rows]

    async def _series(
        self,
        start: date,
        end: date,
        interval: str,
        spec: QuerySpec | None,
    ) -> list[dict[str, Any]]:
        m = self.model
        q = (
            m.measures.revenue
            + m.filter("period_start", "between", (start, end))
            + m.time_grain("period_start", interval)
        )
        q = q + await build_spec_fragment(m, spec, self.db)
        stmt, params = q.compile(m)
        result = await self.db.execute(stmt, params)
        return [dict(r) for r in result.mappings().all()]

    async def _by_customer(
        self,
        start: date,
        end: date,
        spec: QuerySpec | None,
    ) -> list[dict[str, Any]]:
        m = self.model
        q = (
            m.measures.revenue
            + m.dimension("customer_id")
            + m.filter("period_start", "between", (start, end))
        )
        q = q + await build_spec_fragment(m, spec, self.db)
        stmt, params = q.compile(m)
        result = await self.db.execute(stmt, params)
        return [dict(r) for r in result.mappings().all()]
