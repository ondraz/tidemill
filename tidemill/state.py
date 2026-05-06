"""Core state consumer — events → core PostgreSQL tables.

Every event is logged to ``event_log`` (idempotent via ON CONFLICT DO NOTHING).
Entity events upsert the corresponding core tables.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from tidemill.fx import normalize_currency

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from tidemill.events import Event


async def handle_state_event(session: AsyncSession, event: Event) -> None:
    """Log *event* and upsert core tables based on its type."""
    await _log_event(session, event)

    prefix = event.type.split(".")[0]
    handler = _HANDLERS.get(prefix)
    if handler:
        await handler(session, event)


# ── event log ────────────────────────────────────────────────────────────


async def _log_event(session: AsyncSession, event: Event) -> None:
    await session.execute(
        text(
            "INSERT INTO event_log (id, source_id, type, customer_id,"
            " occurred_at, published_at, payload)"
            " VALUES (:id, :src, :type, :cid, :occ, :pub, :payload)"
            " ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": event.id,
            "src": event.source_id,
            "type": event.type,
            "cid": event.customer_id,
            "occ": event.occurred_at,
            "pub": event.published_at,
            "payload": json.dumps(event.payload),
        },
    )


# ── product ──────────────────────────────────────────────────────────────


async def _handle_product(session: AsyncSession, event: Event) -> None:
    p = event.payload
    match event.type:
        case "product.created" | "product.updated":
            await session.execute(
                text(
                    "INSERT INTO product"
                    " (id, source_id, external_id, name, description,"
                    "  active, metadata_, created_at, updated_at)"
                    " VALUES (:id, :src, :eid, :name, :description,"
                    "  :active, :meta, :now, :now)"
                    " ON CONFLICT ON CONSTRAINT uq_product_source DO UPDATE SET"
                    "  name = COALESCE(EXCLUDED.name, product.name),"
                    "  description = COALESCE(EXCLUDED.description, product.description),"
                    "  active = EXCLUDED.active,"
                    "  metadata_ = COALESCE(EXCLUDED.metadata_, product.metadata_),"
                    "  updated_at = EXCLUDED.updated_at"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "src": event.source_id,
                    "eid": p["external_id"],
                    "name": p.get("name"),
                    "description": p.get("description"),
                    "active": p.get("active", True),
                    "meta": json.dumps(p.get("metadata", {})),
                    "now": event.occurred_at,
                },
            )
        case "product.deleted":
            # Mark inactive instead of deleting — plans may still reference it.
            await session.execute(
                text(
                    "UPDATE product SET active = FALSE, updated_at = :now"
                    " WHERE source_id = :src AND external_id = :eid"
                ),
                {"src": event.source_id, "eid": p["external_id"], "now": event.occurred_at},
            )


# ── plan (Stripe price) ──────────────────────────────────────────────────


async def _handle_plan(session: AsyncSession, event: Event) -> None:
    p = event.payload
    match event.type:
        case "plan.created" | "plan.updated":
            # The connector filters non-recurring Stripe Prices, so
            # ``interval`` should always be set.  Skip defensively
            # rather than coercing to a default that would distort
            # the ``plan_interval`` analytics dimension.
            if not p.get("interval"):
                return
            await session.execute(
                text(
                    "INSERT INTO plan"
                    " (id, source_id, external_id, product_id, name,"
                    '  "interval", interval_count, amount_cents, currency,'
                    "  billing_scheme, usage_type, trial_period_days,"
                    "  metadata_, active, created_at)"
                    " VALUES (:id, :src, :eid,"
                    "  (SELECT id FROM product WHERE source_id = :src"
                    "     AND external_id = :prod_eid LIMIT 1),"
                    "  :name, :interval, :ic, :amount, :currency,"
                    "  :scheme, :usage, :trial, :meta, :active, :now)"
                    " ON CONFLICT ON CONSTRAINT uq_plan_source DO UPDATE SET"
                    "  product_id = COALESCE(EXCLUDED.product_id, plan.product_id),"
                    "  name = COALESCE(EXCLUDED.name, plan.name),"
                    '  "interval" = COALESCE(EXCLUDED."interval", plan."interval"),'
                    "  interval_count = EXCLUDED.interval_count,"
                    "  amount_cents = COALESCE(EXCLUDED.amount_cents, plan.amount_cents),"
                    "  currency = COALESCE(EXCLUDED.currency, plan.currency),"
                    "  billing_scheme = COALESCE(EXCLUDED.billing_scheme, plan.billing_scheme),"
                    "  usage_type = COALESCE(EXCLUDED.usage_type, plan.usage_type),"
                    "  trial_period_days = COALESCE("
                    "    EXCLUDED.trial_period_days, plan.trial_period_days),"
                    "  metadata_ = COALESCE(EXCLUDED.metadata_, plan.metadata_),"
                    "  active = EXCLUDED.active"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "src": event.source_id,
                    "eid": p["external_id"],
                    "prod_eid": p.get("product_external_id", ""),
                    "name": p.get("name"),
                    "interval": p["interval"],
                    "ic": p.get("interval_count") or 1,
                    "amount": p.get("amount_cents"),
                    "currency": normalize_currency(p.get("currency")),
                    "scheme": p.get("billing_scheme"),
                    "usage": p.get("usage_type"),
                    "trial": p.get("trial_period_days"),
                    "meta": json.dumps(p.get("metadata", {})),
                    "active": p.get("active", True),
                    "now": event.occurred_at,
                },
            )
        case "plan.deleted":
            # Mark inactive — subscriptions may still reference this plan.
            await session.execute(
                text(
                    "UPDATE plan SET active = FALSE WHERE source_id = :src AND external_id = :eid"
                ),
                {"src": event.source_id, "eid": p["external_id"]},
            )


# ── customer ─────────────────────────────────────────────────────────────


async def _handle_customer(session: AsyncSession, event: Event) -> None:
    p = event.payload
    match event.type:
        case "customer.created" | "customer.updated":
            await session.execute(
                text(
                    "INSERT INTO customer"
                    " (id, source_id, external_id, name, email, country,"
                    " currency, metadata_, created_at, updated_at)"
                    " VALUES (:id, :src, :eid, :name, :email, :country,"
                    "  :currency, :meta, :now, :now)"
                    " ON CONFLICT ON CONSTRAINT uq_customer_source DO UPDATE SET"
                    "  name = COALESCE(EXCLUDED.name, customer.name),"
                    "  email = COALESCE(EXCLUDED.email, customer.email),"
                    "  country = COALESCE(EXCLUDED.country, customer.country),"
                    "  currency = COALESCE(EXCLUDED.currency, customer.currency),"
                    "  metadata_ = COALESCE(EXCLUDED.metadata_, customer.metadata_),"
                    "  updated_at = EXCLUDED.updated_at"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "src": event.source_id,
                    "eid": p["external_id"],
                    "name": p.get("name"),
                    "email": p.get("email"),
                    "country": p.get("country"),
                    "currency": normalize_currency(p.get("currency")),
                    "meta": json.dumps(p.get("metadata", {})),
                    "now": event.occurred_at,
                },
            )
            # Fan Stripe metadata out into typed customer_attribute rows so
            # segments can filter on it.  We resolve the customer's internal
            # id from (source_id, external_id) — the INSERT above may have
            # generated a fresh UUID on first sight, so we re-read here.
            meta = p.get("metadata") or {}
            if meta:
                from tidemill.attributes.ingest import fan_out_customer_metadata

                cust_row = await session.execute(
                    text("SELECT id FROM customer WHERE source_id = :src AND external_id = :eid"),
                    {"src": event.source_id, "eid": p["external_id"]},
                )
                cust = cust_row.mappings().first()
                if cust is not None:
                    await fan_out_customer_metadata(
                        session,
                        source_id=event.source_id,
                        customer_id=cust["id"],
                        metadata=meta,
                        origin="stripe",
                    )
        case "customer.deleted":
            await session.execute(
                text("DELETE FROM customer WHERE source_id = :src AND external_id = :eid"),
                {"src": event.source_id, "eid": p["external_id"]},
            )


# ── subscription ─────────────────────────────────────────────────────────


def _parse_ts(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    return datetime.fromisoformat(val)


async def _handle_subscription(session: AsyncSession, event: Event) -> None:
    p = event.payload
    ext_id = p["external_id"]

    match event.type:
        case "subscription.created":
            await session.execute(
                text(
                    "INSERT INTO subscription"
                    " (id, source_id, external_id, customer_id, plan_id,"
                    "  status, mrr_cents, mrr_base_cents, currency, quantity,"
                    "  started_at, trial_start, trial_end,"
                    "  current_period_start, current_period_end,"
                    "  created_at, updated_at)"
                    " VALUES (:id, :src, :eid,"
                    "  (SELECT id FROM customer WHERE source_id = :src"
                    "     AND external_id = :cust_eid LIMIT 1),"
                    "  (SELECT id FROM plan WHERE source_id = :src"
                    "     AND external_id = :plan_eid LIMIT 1),"
                    "  :status, :mrr, :mrr, :currency, :qty,"
                    "  :started, :ts, :te, :cps, :cpe, :now, :now)"
                    " ON CONFLICT ON CONSTRAINT uq_subscription_source DO UPDATE SET"
                    "  status = EXCLUDED.status,"
                    "  mrr_cents = EXCLUDED.mrr_cents,"
                    "  mrr_base_cents = EXCLUDED.mrr_base_cents,"
                    "  updated_at = EXCLUDED.updated_at"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "src": event.source_id,
                    "eid": ext_id,
                    "cust_eid": p.get("customer_external_id", event.customer_id),
                    "plan_eid": p.get("plan_external_id", ""),
                    "status": p.get("status", "active"),
                    "mrr": p.get("mrr_cents", 0),
                    "currency": normalize_currency(p.get("currency")),
                    "qty": p.get("quantity", 1),
                    "started": _parse_ts(p.get("started_at")),
                    "ts": _parse_ts(p.get("trial_start")),
                    "te": _parse_ts(p.get("trial_end")),
                    "cps": _parse_ts(p.get("current_period_start")),
                    "cpe": _parse_ts(p.get("current_period_end")),
                    "now": event.occurred_at,
                },
            )
        case "subscription.activated" | "subscription.reactivated" | "subscription.resumed":
            await session.execute(
                text(
                    "UPDATE subscription SET"
                    "  status = 'active',"
                    "  mrr_cents = :mrr,"
                    "  ended_at = NULL,"
                    "  updated_at = :now"
                    " WHERE source_id = :src AND external_id = :eid"
                ),
                {
                    "src": event.source_id,
                    "eid": ext_id,
                    "mrr": p.get("mrr_cents", 0),
                    "now": event.occurred_at,
                },
            )
        case "subscription.changed":
            await session.execute(
                text(
                    "UPDATE subscription SET"
                    "  mrr_cents = :mrr,"
                    "  plan_id = COALESCE("
                    "    (SELECT id FROM plan WHERE source_id = :src"
                    "       AND external_id = :plan_eid LIMIT 1),"
                    "    plan_id),"
                    "  quantity = :qty,"
                    "  updated_at = :now"
                    " WHERE source_id = :src AND external_id = :eid"
                ),
                {
                    "src": event.source_id,
                    "eid": ext_id,
                    "mrr": p.get("new_mrr_cents", 0),
                    "plan_eid": p.get("new_plan_external_id", ""),
                    "qty": p.get("new_quantity", 1),
                    "now": event.occurred_at,
                },
            )
        case "subscription.canceled":
            await session.execute(
                text(
                    "UPDATE subscription SET"
                    "  status = 'canceled',"
                    "  cancel_at_period_end = TRUE,"
                    "  canceled_at = :canceled,"
                    "  updated_at = :now"
                    " WHERE source_id = :src AND external_id = :eid"
                ),
                {
                    "src": event.source_id,
                    "eid": ext_id,
                    "canceled": _parse_ts(p.get("canceled_at")) or event.occurred_at,
                    "now": event.occurred_at,
                },
            )
        case "subscription.churned":
            await session.execute(
                text(
                    "UPDATE subscription SET"
                    "  status = 'canceled',"
                    "  mrr_cents = 0,"
                    "  ended_at = :now,"
                    "  updated_at = :now"
                    " WHERE source_id = :src AND external_id = :eid"
                ),
                {"src": event.source_id, "eid": ext_id, "now": event.occurred_at},
            )
        case "subscription.paused":
            await session.execute(
                text(
                    "UPDATE subscription SET"
                    "  status = 'paused',"
                    "  mrr_cents = 0,"
                    "  updated_at = :now"
                    " WHERE source_id = :src AND external_id = :eid"
                ),
                {"src": event.source_id, "eid": ext_id, "now": event.occurred_at},
            )


# ── invoice ──────────────────────────────────────────────────────────────


async def _handle_invoice(session: AsyncSession, event: Event) -> None:
    p = event.payload

    match event.type:
        case "invoice.created":
            await session.execute(
                text(
                    "INSERT INTO invoice"
                    " (id, source_id, external_id, customer_id, subscription_id,"
                    "  status, currency, subtotal_cents, tax_cents, total_cents,"
                    "  period_start, period_end, created_at)"
                    " VALUES (:id, :src, :eid,"
                    "  (SELECT id FROM customer WHERE source_id = :src"
                    "     AND external_id = :cust_eid LIMIT 1),"
                    "  (SELECT id FROM subscription WHERE source_id = :src"
                    "     AND external_id = :sub_eid LIMIT 1),"
                    "  :status, :cur, :sub_cents, :tax, :total,"
                    "  :ps, :pe, :now)"
                    " ON CONFLICT ON CONSTRAINT uq_invoice_source DO UPDATE SET"
                    "  status = EXCLUDED.status,"
                    "  total_cents = EXCLUDED.total_cents"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "src": event.source_id,
                    "eid": p["external_id"],
                    "cust_eid": p.get("customer_external_id", event.customer_id),
                    "sub_eid": p.get("subscription_external_id", ""),
                    "status": p.get("status"),
                    "cur": normalize_currency(p.get("currency")),
                    "sub_cents": p.get("subtotal_cents", 0),
                    "tax": p.get("tax_cents", 0),
                    "total": p.get("total_cents", 0),
                    "ps": _parse_ts(p.get("period_start")),
                    "pe": _parse_ts(p.get("period_end")),
                    "now": event.occurred_at,
                },
            )
        case "invoice.paid":
            await session.execute(
                text(
                    "UPDATE invoice SET status = 'paid', paid_at = :paid"
                    " WHERE source_id = :src AND external_id = :eid"
                ),
                {
                    "src": event.source_id,
                    "eid": p["external_id"],
                    "paid": _parse_ts(p.get("paid_at")) or event.occurred_at,
                },
            )
        case "invoice.voided":
            await session.execute(
                text(
                    "UPDATE invoice SET status = 'void', voided_at = :voided"
                    " WHERE source_id = :src AND external_id = :eid"
                ),
                {
                    "src": event.source_id,
                    "eid": p["external_id"],
                    "voided": _parse_ts(p.get("voided_at")) or event.occurred_at,
                },
            )
        case "invoice.uncollectible":
            await session.execute(
                text(
                    "UPDATE invoice SET status = 'uncollectible'"
                    " WHERE source_id = :src AND external_id = :eid"
                ),
                {"src": event.source_id, "eid": p["external_id"]},
            )


# ── payment ──────────────────────────────────────────────────────────────


async def _handle_payment(session: AsyncSession, event: Event) -> None:
    p = event.payload

    match event.type:
        case "payment.succeeded":
            await session.execute(
                text(
                    "INSERT INTO payment"
                    " (id, source_id, external_id, invoice_id, customer_id,"
                    "  status, amount_cents, currency, payment_method_type,"
                    "  succeeded_at, created_at)"
                    " VALUES (:id, :src, :eid,"
                    "  (SELECT id FROM invoice WHERE source_id = :src"
                    "     AND external_id = :inv_eid LIMIT 1),"
                    "  (SELECT id FROM customer WHERE source_id = :src"
                    "     AND external_id = :cust_eid LIMIT 1),"
                    "  'succeeded', :amount, :cur, :pmt, :now, :now)"
                    " ON CONFLICT ON CONSTRAINT uq_payment_source DO UPDATE SET"
                    "  status = 'succeeded', succeeded_at = EXCLUDED.succeeded_at"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "src": event.source_id,
                    "eid": p["external_id"],
                    "inv_eid": p.get("invoice_external_id", ""),
                    "cust_eid": p.get("customer_external_id", event.customer_id),
                    "amount": p.get("amount_cents", 0),
                    "cur": normalize_currency(p.get("currency")),
                    "pmt": p.get("payment_method_type"),
                    "now": event.occurred_at,
                },
            )
        case "payment.failed":
            await session.execute(
                text(
                    "INSERT INTO payment"
                    " (id, source_id, external_id, invoice_id, customer_id,"
                    "  status, amount_cents, currency, failure_reason,"
                    "  attempt_count, failed_at, created_at)"
                    " VALUES (:id, :src, :eid,"
                    "  (SELECT id FROM invoice WHERE source_id = :src"
                    "     AND external_id = :inv_eid LIMIT 1),"
                    "  (SELECT id FROM customer WHERE source_id = :src"
                    "     AND external_id = :cust_eid LIMIT 1),"
                    "  'failed', :amount, :cur, :reason, :attempts, :now, :now)"
                    " ON CONFLICT ON CONSTRAINT uq_payment_source DO UPDATE SET"
                    "  status = 'failed',"
                    "  failure_reason = EXCLUDED.failure_reason,"
                    "  attempt_count = EXCLUDED.attempt_count,"
                    "  failed_at = EXCLUDED.failed_at"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "src": event.source_id,
                    "eid": p["external_id"],
                    "inv_eid": p.get("invoice_external_id", ""),
                    "cust_eid": p.get("customer_external_id", event.customer_id),
                    "amount": p.get("amount_cents", 0),
                    "cur": normalize_currency(p.get("currency")),
                    "reason": p.get("failure_reason"),
                    "attempts": p.get("attempt_count"),
                    "now": event.occurred_at,
                },
            )
        case "payment.refunded":
            await session.execute(
                text(
                    "UPDATE payment SET"
                    "  status = 'refunded',"
                    "  refunded_at = :refunded"
                    " WHERE source_id = :src AND external_id = :eid"
                ),
                {
                    "src": event.source_id,
                    "eid": p["external_id"],
                    "refunded": _parse_ts(p.get("refunded_at")) or event.occurred_at,
                },
            )


# ── dispatch table ───────────────────────────────────────────────────────

_HANDLERS: dict[str, Any] = {
    "product": _handle_product,
    "plan": _handle_plan,
    "customer": _handle_customer,
    "subscription": _handle_subscription,
    "invoice": _handle_invoice,
    "payment": _handle_payment,
}
