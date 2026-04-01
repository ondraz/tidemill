"""RetentionMetric — query methods: cohort_matrix, nrr, grr."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from subscriptions.metrics.base import Metric, QuerySpec
from subscriptions.metrics.registry import register
from subscriptions.metrics.retention.cubes import RetentionCohortCube

if TYPE_CHECKING:
    from datetime import date


@register
class RetentionMetric(Metric):
    name = "retention"
    model = RetentionCohortCube

    @property
    def dependencies(self) -> list[str]:
        return ["mrr"]

    async def query(self, params: dict[str, Any], spec: QuerySpec | None = None) -> Any:
        match params.get("query_type", "cohort_matrix"):
            case "cohort_matrix":
                return await self._cohort_matrix(
                    params["start"],
                    params["end"],
                    spec,
                )
            case "nrr":
                return await self._nrr(params["start"], params["end"])
            case "grr":
                return await self._grr(params["start"], params["end"])
            case other:
                raise ValueError(f"Unknown query_type: {other}")

    async def _cohort_matrix(
        self,
        start: date,
        end: date,
        spec: QuerySpec | None,
    ) -> list[dict[str, Any]]:
        m = self.model

        q = (
            m.measures.cohort_size
            + m.measures.active_count
            + m.dimension("cohort_month")
            + m.dimension("active_month")
            + m.filter("cohort_month_time", "between", (start, end))
        )
        if spec:
            q = q + m.apply_spec(spec)

        stmt, params = q.compile(m)
        result = await self.db.execute(stmt, params)
        return [dict(r) for r in result.mappings().all()]

    async def _nrr(self, start: date, end: date) -> float | None:
        """Net Revenue Retention = (start_mrr + expansion - contraction - churn) / start_mrr."""
        return await self._revenue_retention(start, end, include_expansion=True)

    async def _grr(self, start: date, end: date) -> float | None:
        """Gross Revenue Retention = (start_mrr - contraction - churn) / start_mrr."""
        return await self._revenue_retention(start, end, include_expansion=False)

    async def _revenue_retention(
        self,
        start: date,
        end: date,
        *,
        include_expansion: bool,
    ) -> float | None:
        from subscriptions.metrics.mrr.cubes import MRRMovementCube, MRRSnapshotCube

        # Get MRR at period start
        sm = MRRSnapshotCube
        sq = sm.measures.mrr + sm.filter("snapshot_at", "<", start)
        stmt, params = sq.compile(sm)
        result = await self.db.execute(stmt, params)
        rows = result.mappings().all()
        start_mrr = rows[0]["mrr"] if rows and rows[0]["mrr"] else 0
        if start_mrr == 0:
            return None

        # Get movements in period
        mm = MRRMovementCube
        mq = (
            mm.measures.amount
            + mm.dimension("movement_type")
            + mm.filter("occurred_at", "between", (start, end))
        )
        stmt, params = mq.compile(mm)
        result = await self.db.execute(stmt, params)
        by_type = {r["movement_type"]: r["amount_base"] for r in result.mappings().all()}

        contraction = abs(by_type.get("contraction", 0))
        churn = abs(by_type.get("churn", 0))

        if include_expansion:
            expansion = by_type.get("expansion", 0) + by_type.get("reactivation", 0)
            return float((start_mrr + expansion - contraction - churn) / start_mrr)

        return float((start_mrr - contraction - churn) / start_mrr)
