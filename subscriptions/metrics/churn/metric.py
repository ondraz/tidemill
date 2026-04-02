"""ChurnMetric — query methods and event handler."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from subscriptions.metrics.base import Metric, QuerySpec
from subscriptions.metrics.churn.cubes import ChurnCustomerStateCube, ChurnEventCube
from subscriptions.metrics.registry import register

if TYPE_CHECKING:
    from datetime import date

    from subscriptions.events import Event


@register
class ChurnMetric(Metric):
    name = "churn"
    event_model = ChurnEventCube
    state_model = ChurnCustomerStateCube

    @property
    def event_types(self) -> list[str]:
        return [
            "subscription.created",
            "subscription.activated",
            "subscription.reactivated",
            "subscription.churned",
            "subscription.canceled",
        ]

    async def handle_event(self, event: Event) -> None:
        p = event.payload

        match event.type:
            case "subscription.created" | "subscription.activated" | "subscription.reactivated":
                await self.db.execute(
                    text(
                        "INSERT INTO metric_churn_customer_state"
                        " (id, source_id, customer_id, active_subscriptions,"
                        "  first_active_at)"
                        " VALUES (:id, :src, :cid, 1, :now)"
                        " ON CONFLICT ON CONSTRAINT uq_churn_state_customer"
                        " DO UPDATE SET"
                        "  active_subscriptions ="
                        "    metric_churn_customer_state.active_subscriptions + 1,"
                        "  first_active_at = COALESCE("
                        "    metric_churn_customer_state.first_active_at,"
                        "    EXCLUDED.first_active_at),"
                        "  churned_at = NULL"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "src": event.source_id,
                        "cid": event.customer_id,
                        "now": event.occurred_at,
                    },
                )

            case "subscription.churned":
                # Decrement active count
                await self.db.execute(
                    text(
                        "UPDATE metric_churn_customer_state SET"
                        "  active_subscriptions ="
                        "    GREATEST(active_subscriptions - 1, 0)"
                        " WHERE source_id = :src AND customer_id = :cid"
                    ),
                    {"src": event.source_id, "cid": event.customer_id},
                )
                # Check if fully churned (0 active) → set churned_at + logo event
                result = await self.db.execute(
                    text(
                        "UPDATE metric_churn_customer_state"
                        " SET churned_at = :now"
                        " WHERE source_id = :src AND customer_id = :cid"
                        "   AND active_subscriptions = 0"
                        " RETURNING id"
                    ),
                    {
                        "src": event.source_id,
                        "cid": event.customer_id,
                        "now": event.occurred_at,
                    },
                )
                if result.fetchone() is not None:
                    await self.db.execute(
                        text(
                            "INSERT INTO metric_churn_event"
                            " (id, event_id, source_id, customer_id,"
                            "  churn_type, mrr_cents, occurred_at)"
                            " VALUES (:id, :eid, :src, :cid,"
                            "  'logo', :mrr, :now)"
                            " ON CONFLICT (event_id) DO NOTHING"
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "eid": event.id + ":logo",
                            "src": event.source_id,
                            "cid": event.customer_id,
                            "mrr": p.get("prev_mrr_cents", 0),
                            "now": event.occurred_at,
                        },
                    )
                # Always record revenue churn event
                await self.db.execute(
                    text(
                        "INSERT INTO metric_churn_event"
                        " (id, event_id, source_id, customer_id,"
                        "  churn_type, mrr_cents, occurred_at)"
                        " VALUES (:id, :eid, :src, :cid,"
                        "  'revenue', :mrr, :now)"
                        " ON CONFLICT (event_id) DO NOTHING"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "eid": event.id + ":revenue",
                        "src": event.source_id,
                        "cid": event.customer_id,
                        "mrr": p.get("prev_mrr_cents", 0),
                        "now": event.occurred_at,
                    },
                )

            case "subscription.canceled":
                await self.db.execute(
                    text(
                        "INSERT INTO metric_churn_event"
                        " (id, event_id, source_id, customer_id,"
                        "  churn_type, cancel_reason, mrr_cents, occurred_at)"
                        " VALUES (:id, :eid, :src, :cid,"
                        "  'canceled', :reason, :mrr, :now)"
                        " ON CONFLICT (event_id) DO NOTHING"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "eid": event.id,
                        "src": event.source_id,
                        "cid": event.customer_id,
                        "reason": p.get("cancel_reason"),
                        "mrr": p.get("mrr_cents", 0),
                        "now": event.occurred_at,
                    },
                )

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

        churn_amount = abs(rows[0]["amount_base"]) if rows and rows[0]["amount_base"] else 0

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
