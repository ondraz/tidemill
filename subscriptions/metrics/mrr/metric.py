"""MrrMetric — query methods and event handler."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from subscriptions.metrics.base import Metric, QuerySpec
from subscriptions.metrics.mrr.cubes import MRRMovementCube, MRRSnapshotCube
from subscriptions.metrics.registry import register

if TYPE_CHECKING:
    from datetime import date

    from subscriptions.events import Event


@register
class MrrMetric(Metric):
    name = "mrr"
    model = MRRSnapshotCube
    movement_model = MRRMovementCube

    @property
    def event_types(self) -> list[str]:
        return [
            "subscription.created",
            "subscription.activated",
            "subscription.changed",
            "subscription.churned",
            "subscription.reactivated",
            "subscription.paused",
            "subscription.resumed",
        ]

    async def handle_event(self, event: Event) -> None:
        from subscriptions.fx import to_base_cents

        p = event.payload
        ext_id = p["external_id"]

        match event.type:
            case "subscription.created" | "subscription.activated":
                mrr = p.get("mrr_cents", 0)
                currency = p.get("currency", "USD") or "USD"
                mrr_base = await to_base_cents(mrr, currency, event.occurred_at.date(), self.db)
                await self._upsert_snapshot(
                    event,
                    ext_id,
                    mrr,
                    mrr_base,
                    currency,
                )
                await self._append_movement(
                    event,
                    ext_id,
                    "new",
                    mrr,
                    mrr_base,
                    currency,
                )

            case "subscription.changed":
                prev_mrr = p.get("prev_mrr_cents", 0)
                new_mrr = p.get("new_mrr_cents", 0)
                currency = p.get("currency", "USD") or "USD"
                new_mrr_base = await to_base_cents(
                    new_mrr, currency, event.occurred_at.date(), self.db
                )
                await self._upsert_snapshot(
                    event,
                    ext_id,
                    new_mrr,
                    new_mrr_base,
                    currency,
                )
                delta = new_mrr - prev_mrr
                delta_base = await to_base_cents(
                    delta, currency, event.occurred_at.date(), self.db
                )
                movement = "expansion" if delta > 0 else "contraction"
                await self._append_movement(
                    event,
                    ext_id,
                    movement,
                    delta,
                    delta_base,
                    currency,
                )

            case "subscription.churned" | "subscription.paused":
                prev_mrr = p.get("prev_mrr_cents", 0) or p.get("mrr_cents", 0)
                currency = p.get("currency", "USD") or "USD"
                prev_mrr_base = await to_base_cents(
                    prev_mrr, currency, event.occurred_at.date(), self.db
                )
                await self._upsert_snapshot(event, ext_id, 0, 0, currency)
                await self._append_movement(
                    event,
                    ext_id,
                    "churn",
                    -prev_mrr,
                    -prev_mrr_base,
                    currency,
                )

            case "subscription.reactivated" | "subscription.resumed":
                mrr = p.get("mrr_cents", 0)
                currency = p.get("currency", "USD") or "USD"
                mrr_base = await to_base_cents(mrr, currency, event.occurred_at.date(), self.db)
                await self._upsert_snapshot(
                    event,
                    ext_id,
                    mrr,
                    mrr_base,
                    currency,
                )
                await self._append_movement(
                    event,
                    ext_id,
                    "reactivation",
                    mrr,
                    mrr_base,
                    currency,
                )

    async def _upsert_snapshot(
        self,
        event: Event,
        subscription_ext_id: str,
        mrr_cents: int,
        mrr_base_cents: int,
        currency: str,
    ) -> None:
        await self.db.execute(
            text(
                "INSERT INTO metric_mrr_snapshot"
                " (id, source_id, customer_id, subscription_id,"
                "  mrr_cents, mrr_base_cents, currency, snapshot_at)"
                " VALUES (:id, :src, :cid, :sid, :mrr, :mrrb, :cur, :at)"
                " ON CONFLICT ON CONSTRAINT uq_mrr_snapshot_sub DO UPDATE SET"
                "  mrr_cents = EXCLUDED.mrr_cents,"
                "  mrr_base_cents = EXCLUDED.mrr_base_cents,"
                "  snapshot_at = EXCLUDED.snapshot_at"
            ),
            {
                "id": str(uuid.uuid4()),
                "src": event.source_id,
                "cid": event.customer_id,
                "sid": subscription_ext_id,
                "mrr": mrr_cents,
                "mrrb": mrr_base_cents,
                "cur": currency,
                "at": event.occurred_at,
            },
        )

    async def _append_movement(
        self,
        event: Event,
        subscription_ext_id: str,
        movement_type: str,
        amount_cents: int,
        amount_base_cents: int,
        currency: str,
    ) -> None:
        await self.db.execute(
            text(
                "INSERT INTO metric_mrr_movement"
                " (id, event_id, source_id, customer_id, subscription_id,"
                "  movement_type, amount_cents, amount_base_cents, currency, occurred_at)"
                " VALUES (:id, :eid, :src, :cid, :sid, :mt, :amt, :amtb, :cur, :at)"
                " ON CONFLICT (event_id) DO NOTHING"
            ),
            {
                "id": str(uuid.uuid4()),
                "eid": event.id,
                "src": event.source_id,
                "cid": event.customer_id,
                "sid": subscription_ext_id,
                "mt": movement_type,
                "amt": amount_cents,
                "amtb": amount_base_cents,
                "cur": currency,
                "at": event.occurred_at,
            },
        )

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
