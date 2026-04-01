"""MrrMetric — query methods: current, series, breakdown, arr."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from subscriptions.metrics.base import Metric, QuerySpec
from subscriptions.metrics.mrr.cubes import MRRMovementCube, MRRSnapshotCube
from subscriptions.metrics.registry import register

if TYPE_CHECKING:
    from datetime import date


@register
class MrrMetric(Metric):
    name = "mrr"
    model = MRRSnapshotCube
    movement_model = MRRMovementCube

    async def query(self, params: dict[str, Any], spec: QuerySpec | None = None) -> Any:
        match params.get("query_type"):
            case "current":
                return await self._current_mrr(params.get("at"), spec)
            case "series":
                return await self._mrr_series(
                    params["start"],
                    params["end"],
                    params.get("interval", "month"),
                    spec,
                )
            case "breakdown":
                return await self._mrr_breakdown(params["start"], params["end"], spec)
            case "arr":
                mrr = await self._current_mrr(params.get("at"), spec)
                if isinstance(mrr, list):
                    return [{**row, "arr": row.get("mrr", 0) * 12} for row in mrr]
                return mrr * 12
            case other:
                raise ValueError(f"Unknown query_type: {other}")

    async def _current_mrr(
        self,
        at: date | None,
        spec: QuerySpec | None,
    ) -> Any:
        m = self.model
        use_original = spec and "currency" in (spec.dimensions or [])
        measure = m.measures.mrr_original if use_original else m.measures.mrr

        q = measure + m.where("s.mrr_base_cents", ">", 0)
        if at:
            q = q + m.filter("snapshot_at", "<=", at)
        if spec:
            q = q + m.apply_spec(spec)

        stmt, params = q.compile(m)
        result = await self.db.execute(stmt, params)
        rows = result.mappings().all()

        if not spec or not spec.dimensions:
            return rows[0]["mrr"] if rows else 0
        return [dict(r) for r in rows]

    async def _mrr_series(
        self,
        start: date,
        end: date,
        interval: str,
        spec: QuerySpec | None,
    ) -> list[dict[str, Any]]:
        mm = self.movement_model

        q = (
            mm.measures.amount
            + mm.filter("occurred_at", "between", (start, end))
            + mm.time_grain("occurred_at", interval)
        )
        if spec:
            q = q + mm.apply_spec(spec)

        stmt, params = q.compile(mm)
        result = await self.db.execute(stmt, params)
        return [dict(r) for r in result.mappings().all()]

    async def _mrr_breakdown(
        self,
        start: date,
        end: date,
        spec: QuerySpec | None,
    ) -> list[dict[str, Any]]:
        mm = self.movement_model

        q = (
            mm.measures.amount
            + mm.dimension("movement_type")
            + mm.filter("occurred_at", "between", (start, end))
        )
        if spec:
            q = q + mm.apply_spec(spec)

        stmt, params = q.compile(mm)
        result = await self.db.execute(stmt, params)
        return [dict(r) for r in result.mappings().all()]
