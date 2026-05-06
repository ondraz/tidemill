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


# ── vendor ───────────────────────────────────────────────────────────────


async def _handle_vendor(session: AsyncSession, event: Event) -> None:
    p = event.payload
    match event.type:
        case "vendor.created" | "vendor.updated":
            await session.execute(
                text(
                    "INSERT INTO vendor"
                    " (id, source_id, external_id, name, email, country,"
                    "  currency, active, metadata_, created_at, updated_at)"
                    " VALUES (:id, :src, :eid, :name, :email, :country,"
                    "  :currency, :active, :meta, :now, :now)"
                    " ON CONFLICT ON CONSTRAINT uq_vendor_source DO UPDATE SET"
                    "  name = COALESCE(EXCLUDED.name, vendor.name),"
                    "  email = COALESCE(EXCLUDED.email, vendor.email),"
                    "  country = COALESCE(EXCLUDED.country, vendor.country),"
                    "  currency = COALESCE(EXCLUDED.currency, vendor.currency),"
                    "  active = EXCLUDED.active,"
                    "  metadata_ = COALESCE(EXCLUDED.metadata_, vendor.metadata_),"
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
                    "active": p.get("active", True),
                    "meta": json.dumps(p.get("metadata", {})),
                    "now": event.occurred_at,
                },
            )
        case "vendor.deleted":
            await session.execute(
                text("DELETE FROM vendor WHERE source_id = :src AND external_id = :eid"),
                {"src": event.source_id, "eid": p["external_id"]},
            )


# ── account (chart of accounts) ──────────────────────────────────────────


async def _handle_account(session: AsyncSession, event: Event) -> None:
    p = event.payload
    match event.type:
        case "account.created" | "account.updated":
            await session.execute(
                text(
                    "INSERT INTO account"
                    " (id, source_id, external_id, name, account_type,"
                    "  account_subtype, parent_external_id, currency, active,"
                    "  metadata_, created_at, updated_at)"
                    " VALUES (:id, :src, :eid, :name, :atype, :asubtype,"
                    "  :parent, :currency, :active, :meta, :now, :now)"
                    " ON CONFLICT ON CONSTRAINT uq_account_source DO UPDATE SET"
                    "  name = EXCLUDED.name,"
                    "  account_type = EXCLUDED.account_type,"
                    "  account_subtype = EXCLUDED.account_subtype,"
                    "  parent_external_id = EXCLUDED.parent_external_id,"
                    "  currency = EXCLUDED.currency,"
                    "  active = EXCLUDED.active,"
                    "  metadata_ = EXCLUDED.metadata_,"
                    "  updated_at = EXCLUDED.updated_at"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "src": event.source_id,
                    "eid": p["external_id"],
                    "name": p.get("name"),
                    "atype": p.get("account_type", "other"),
                    "asubtype": p.get("account_subtype"),
                    "parent": p.get("parent_external_id"),
                    "currency": normalize_currency(p.get("currency")),
                    "active": p.get("active", True),
                    "meta": json.dumps(p.get("metadata", {})),
                    "now": event.occurred_at,
                },
            )


# ── bill ─────────────────────────────────────────────────────────────────


async def _upsert_lines(
    session: AsyncSession,
    *,
    table: str,
    parent_col: str,
    parent_id: str,
    lines: list[dict[str, Any]],
) -> None:
    """Replace all line rows for a bill/expense with the freshly translated set.

    Bill/expense lines have no stable external ID across platforms — many
    accounting systems regenerate line IDs on every update. Replacing in
    bulk (DELETE + INSERT) is simpler and idempotent than diff-based upserts.
    """
    await session.execute(
        text(f"DELETE FROM {table} WHERE {parent_col} = :pid"),
        {"pid": parent_id},
    )
    for line in lines:
        await session.execute(
            text(
                f"INSERT INTO {table}"
                f" (id, {parent_col}, account_id, description, quantity,"
                "  amount_cents, amount_base_cents, currency, dimensions)"
                " VALUES (:id, :pid,"
                "  (SELECT id FROM account WHERE source_id = :src"
                "     AND external_id = :acct_eid LIMIT 1),"
                "  :desc, :qty, :amt, :amtb, :cur, :dims)"
            ),
            {
                "id": str(uuid.uuid4()),
                "pid": parent_id,
                "src": line["source_id"],
                "acct_eid": line.get("account_external_id", ""),
                "desc": line.get("description"),
                "qty": line.get("quantity"),
                "amt": line.get("amount_cents", 0),
                "amtb": line.get("amount_base_cents", 0),
                "cur": normalize_currency(line.get("currency")),
                "dims": json.dumps(line.get("dimensions") or {}),
            },
        )


async def _resolve_id(
    session: AsyncSession, table: str, source_id: str, external_id: str
) -> str | None:
    result = await session.execute(
        text(f"SELECT id FROM {table} WHERE source_id = :src AND external_id = :eid"),
        {"src": source_id, "eid": external_id},
    )
    row = result.mappings().first()
    return row["id"] if row else None


async def _handle_bill(session: AsyncSession, event: Event) -> None:
    p = event.payload
    ext_id = p["external_id"]

    match event.type:
        case "bill.created" | "bill.updated":
            await session.execute(
                text(
                    "INSERT INTO bill"
                    " (id, source_id, external_id, vendor_id, status, doc_number,"
                    "  currency, subtotal_cents, subtotal_base_cents,"
                    "  tax_cents, tax_base_cents, total_cents, total_base_cents,"
                    "  txn_date, due_date, memo, metadata_, created_at, updated_at)"
                    " VALUES (:id, :src, :eid,"
                    "  (SELECT id FROM vendor WHERE source_id = :src"
                    "     AND external_id = :vendor_eid LIMIT 1),"
                    "  :status, :doc, :cur, :sub, :subb, :tax, :taxb,"
                    "  :total, :totalb, :txn, :due, :memo, :meta, :now, :now)"
                    " ON CONFLICT ON CONSTRAINT uq_bill_source DO UPDATE SET"
                    "  status = EXCLUDED.status,"
                    "  doc_number = EXCLUDED.doc_number,"
                    "  currency = EXCLUDED.currency,"
                    "  subtotal_cents = EXCLUDED.subtotal_cents,"
                    "  subtotal_base_cents = EXCLUDED.subtotal_base_cents,"
                    "  tax_cents = EXCLUDED.tax_cents,"
                    "  tax_base_cents = EXCLUDED.tax_base_cents,"
                    "  total_cents = EXCLUDED.total_cents,"
                    "  total_base_cents = EXCLUDED.total_base_cents,"
                    "  txn_date = EXCLUDED.txn_date,"
                    "  due_date = EXCLUDED.due_date,"
                    "  memo = EXCLUDED.memo,"
                    "  metadata_ = EXCLUDED.metadata_,"
                    "  updated_at = EXCLUDED.updated_at"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "src": event.source_id,
                    "eid": ext_id,
                    "vendor_eid": p.get("vendor_external_id", ""),
                    "status": p.get("status", "open"),
                    "doc": p.get("doc_number"),
                    "cur": normalize_currency(p.get("currency")),
                    "sub": p.get("subtotal_cents", 0),
                    "subb": p.get("subtotal_base_cents", 0),
                    "tax": p.get("tax_cents", 0),
                    "taxb": p.get("tax_base_cents", 0),
                    "total": p.get("total_cents", 0),
                    "totalb": p.get("total_base_cents", 0),
                    "txn": _parse_ts(p.get("txn_date")),
                    "due": _parse_ts(p.get("due_date")),
                    "memo": p.get("memo"),
                    "meta": json.dumps(p.get("metadata", {})),
                    "now": event.occurred_at,
                },
            )
            bill_id = await _resolve_id(session, "bill", event.source_id, ext_id)
            lines = p.get("lines") or []
            if bill_id and lines:
                for line in lines:
                    line["source_id"] = event.source_id
                await _upsert_lines(
                    session,
                    table="bill_line",
                    parent_col="bill_id",
                    parent_id=bill_id,
                    lines=lines,
                )
        case "bill.paid":
            await session.execute(
                text(
                    "UPDATE bill SET status = 'paid', paid_at = :paid,"
                    "  updated_at = :now"
                    " WHERE source_id = :src AND external_id = :eid"
                ),
                {
                    "src": event.source_id,
                    "eid": ext_id,
                    "paid": _parse_ts(p.get("paid_at")) or event.occurred_at,
                    "now": event.occurred_at,
                },
            )
        case "bill.voided":
            await session.execute(
                text(
                    "UPDATE bill SET status = 'voided', voided_at = :voided,"
                    "  updated_at = :now"
                    " WHERE source_id = :src AND external_id = :eid"
                ),
                {
                    "src": event.source_id,
                    "eid": ext_id,
                    "voided": _parse_ts(p.get("voided_at")) or event.occurred_at,
                    "now": event.occurred_at,
                },
            )


# ── expense (cash/credit/check direct expense, no bill) ──────────────────


async def _handle_expense(session: AsyncSession, event: Event) -> None:
    p = event.payload
    ext_id = p["external_id"]

    match event.type:
        case "expense.created" | "expense.updated":
            await session.execute(
                text(
                    "INSERT INTO expense"
                    " (id, source_id, external_id, vendor_id, payment_type,"
                    "  doc_number, currency, subtotal_cents, subtotal_base_cents,"
                    "  tax_cents, tax_base_cents, total_cents, total_base_cents,"
                    "  txn_date, memo, metadata_, created_at, updated_at)"
                    " VALUES (:id, :src, :eid,"
                    "  (SELECT id FROM vendor WHERE source_id = :src"
                    "     AND external_id = :vendor_eid LIMIT 1),"
                    "  :ptype, :doc, :cur, :sub, :subb, :tax, :taxb,"
                    "  :total, :totalb, :txn, :memo, :meta, :now, :now)"
                    " ON CONFLICT ON CONSTRAINT uq_expense_source DO UPDATE SET"
                    "  payment_type = EXCLUDED.payment_type,"
                    "  doc_number = EXCLUDED.doc_number,"
                    "  currency = EXCLUDED.currency,"
                    "  subtotal_cents = EXCLUDED.subtotal_cents,"
                    "  subtotal_base_cents = EXCLUDED.subtotal_base_cents,"
                    "  tax_cents = EXCLUDED.tax_cents,"
                    "  tax_base_cents = EXCLUDED.tax_base_cents,"
                    "  total_cents = EXCLUDED.total_cents,"
                    "  total_base_cents = EXCLUDED.total_base_cents,"
                    "  txn_date = EXCLUDED.txn_date,"
                    "  memo = EXCLUDED.memo,"
                    "  metadata_ = EXCLUDED.metadata_,"
                    "  updated_at = EXCLUDED.updated_at"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "src": event.source_id,
                    "eid": ext_id,
                    "vendor_eid": p.get("vendor_external_id", ""),
                    "ptype": p.get("payment_type", "other"),
                    "doc": p.get("doc_number"),
                    "cur": normalize_currency(p.get("currency")),
                    "sub": p.get("subtotal_cents", 0),
                    "subb": p.get("subtotal_base_cents", 0),
                    "tax": p.get("tax_cents", 0),
                    "taxb": p.get("tax_base_cents", 0),
                    "total": p.get("total_cents", 0),
                    "totalb": p.get("total_base_cents", 0),
                    "txn": _parse_ts(p.get("txn_date")),
                    "memo": p.get("memo"),
                    "meta": json.dumps(p.get("metadata", {})),
                    "now": event.occurred_at,
                },
            )
            expense_id = await _resolve_id(session, "expense", event.source_id, ext_id)
            lines = p.get("lines") or []
            if expense_id and lines:
                for line in lines:
                    line["source_id"] = event.source_id
                await _upsert_lines(
                    session,
                    table="expense_line",
                    parent_col="expense_id",
                    parent_id=expense_id,
                    lines=lines,
                )
        case "expense.voided":
            await session.execute(
                text(
                    "UPDATE expense SET voided_at = :voided, updated_at = :now"
                    " WHERE source_id = :src AND external_id = :eid"
                ),
                {
                    "src": event.source_id,
                    "eid": ext_id,
                    "voided": _parse_ts(p.get("voided_at")) or event.occurred_at,
                    "now": event.occurred_at,
                },
            )


# ── bill_payment (payment applied to a bill) ─────────────────────────────


async def _handle_bill_payment(session: AsyncSession, event: Event) -> None:
    p = event.payload

    match event.type:
        case "bill_payment.created":
            await session.execute(
                text(
                    "INSERT INTO bill_payment"
                    " (id, source_id, external_id, bill_id, paid_at,"
                    "  amount_cents, amount_base_cents, currency, metadata_, created_at)"
                    " VALUES (:id, :src, :eid,"
                    "  (SELECT id FROM bill WHERE source_id = :src"
                    "     AND external_id = :bill_eid LIMIT 1),"
                    "  :paid, :amt, :amtb, :cur, :meta, :now)"
                    " ON CONFLICT ON CONSTRAINT uq_bill_payment_source DO UPDATE SET"
                    "  paid_at = EXCLUDED.paid_at,"
                    "  amount_cents = EXCLUDED.amount_cents,"
                    "  amount_base_cents = EXCLUDED.amount_base_cents"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "src": event.source_id,
                    "eid": p["external_id"],
                    "bill_eid": p.get("bill_external_id", ""),
                    "paid": _parse_ts(p.get("paid_at")) or event.occurred_at,
                    "amt": p.get("amount_cents", 0),
                    "amtb": p.get("amount_base_cents", 0),
                    "cur": normalize_currency(p.get("currency")),
                    "meta": json.dumps(p.get("metadata", {})),
                    "now": event.occurred_at,
                },
            )


# ── dispatch table ───────────────────────────────────────────────────────

_HANDLERS: dict[str, Any] = {
    "customer": _handle_customer,
    "subscription": _handle_subscription,
    "invoice": _handle_invoice,
    "payment": _handle_payment,
    "vendor": _handle_vendor,
    "account": _handle_account,
    "bill": _handle_bill,
    "bill_payment": _handle_bill_payment,
    "expense": _handle_expense,
}
