"""ChurnMetric — query methods: logo, revenue."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from subscriptions.metrics.base import Metric, QuerySpec
from subscriptions.metrics.churn.cubes import ChurnCustomerStateCube, ChurnEventCube
from subscriptions.metrics.registry import register

if TYPE_CHECKING:
    from datetime import date


@register
class ChurnMetric(Metric):
    name = "churn"
    event_model = ChurnEventCube
    state_model = ChurnCustomerStateCube

    async def query(self, params: dict[str, Any], spec: QuerySpec | None = None) -> Any:
        churn_type = params.get("type", "logo")
        start, end = params["start"], params["end"]

        match churn_type:
            case "logo":
                return await self._logo_churn(start, end, spec)
            case "revenue":
                return await self._revenue_churn(start, end, spec)
            case other:
                raise ValueError(f"Unknown churn type: {other}")

    async def _logo_churn(
        self,
        start: date,
        end: date,
        spec: QuerySpec | None,
    ) -> Any:
        em = self.event_model

        # Numerator: customers who churned in the period
        q = (
            em.measures.count
            + em.filter("churn_type", "=", "logo")
            + em.filter("occurred_at", "between", (start, end))
        )
        if spec:
            q = q + em.apply_spec(spec)

        stmt, params = q.compile(em)
        result = await self.db.execute(stmt, params)
        rows = result.mappings().all()

        if spec and spec.dimensions:
            return [dict(r) for r in rows]

        churned = rows[0]["churn_count"] if rows else 0

        # Denominator: customers active at period start
        sm = self.state_model
        dq = (
            sm.measures.count
            + sm.where("cs.first_active_at", "<", start)
            + sm.where("COALESCE(cs.churned_at, '9999-12-31'::timestamptz)", ">=", start)
        )
        dstmt, dparams = dq.compile(sm)
        dresult = await self.db.execute(dstmt, dparams)
        drows = dresult.mappings().all()
        active_start = drows[0]["customer_count"] if drows else 0

        if active_start == 0:
            return None
        return churned / active_start

    async def _revenue_churn(
        self,
        start: date,
        end: date,
        spec: QuerySpec | None,
    ) -> Any:
        from subscriptions.metrics.mrr.cubes import MRRMovementCube, MRRSnapshotCube

        mm = MRRMovementCube

        # Numerator: absolute churn amount in the period
        q = (
            mm.measures.amount
            + mm.filter("movement_type", "=", "churn")
            + mm.filter("occurred_at", "between", (start, end))
        )
        if spec:
            q = q + mm.apply_spec(spec)

        stmt, params = q.compile(mm)
        result = await self.db.execute(stmt, params)
        rows = result.mappings().all()

        if spec and spec.dimensions:
            return [dict(r) for r in rows]

        churn_amount = abs(rows[0]["amount_usd"]) if rows and rows[0]["amount_usd"] else 0

        # Denominator: MRR at period start
        sm = MRRSnapshotCube
        dq = sm.measures.mrr + sm.filter("snapshot_at", "<", start)
        dstmt, dparams = dq.compile(sm)
        dresult = await self.db.execute(dstmt, dparams)
        drows = dresult.mappings().all()
        start_mrr = drows[0]["mrr"] if drows and drows[0]["mrr"] else 0

        if start_mrr == 0:
            return None
        return churn_amount / start_mrr
