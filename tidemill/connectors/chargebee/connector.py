"""Chargebee webhook connector.

Chargebee 2.0 webhook payload shape (every event type):

```
{
  "id": "ev_xxx",
  "occurred_at": 1700000000,
  "event_type": "subscription_created",
  "content": { "subscription": {...}, "customer": {...}, "invoice": {...}, ... }
}
```

The ``content`` block holds whatever entities are relevant for the event.
Our ``_HANDLERS`` map dispatches on ``event_type``; each handler picks
the relevant sub-objects out of ``content`` and emits canonical events.

Currency: Chargebee returns amounts in the smallest unit (cents for
USD/EUR/GBP, whole units for JPY/KRW) — same convention as Stripe — so
no scaling is needed when populating ``*_cents`` columns.
"""

from __future__ import annotations

import base64
import binascii
import hmac
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from tidemill.connectors.base import WebhookConnector
from tidemill.connectors.registry import register
from tidemill.events import Event, make_event_id

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from fastapi import APIRouter


# ── Canonical mapping tables ─────────────────────────────────────────────

# Chargebee ``Subscription.status`` → canonical subscription status. Note
# that ``non_renewing`` is still considered ``active`` for MRR purposes —
# the subscription is billing normally but flagged for cancellation at the
# end of the current period (we set ``pending_cancellation=true``).
_STATUS_MAP: dict[str, str] = {
    "active": "active",
    "non_renewing": "active",
    "in_trial": "trialing",
    "future": "trialing",
    "paused": "paused",
    "cancelled": "canceled",
    "transferred": "canceled",
}

# Chargebee ``period_unit`` → canonical interval. Chargebee uses
# singular ("day", "week", "month", "year") which already matches.
_INTERVAL_MAP: dict[str, str] = {
    "day": "day",
    "week": "week",
    "month": "month",
    "year": "year",
}

# Chargebee ``ItemPrice.pricing_model`` → canonical pricing model.
_PRICING_MODEL_MAP: dict[str, str] = {
    "flat_fee": "flat",
    "per_unit": "flat",  # demoted unless usage_type implies metered
    "tiered": "tiered",
    "stairstep": "tiered",
    "volume": "volume",
}

# Chargebee ``InvoiceLineItem.entity_type`` (and proration flag) →
# canonical line-item kind. Discount and credit-note lines come through
# with their own type buckets the resolver picks up via amount sign.
_LINE_ENTITY_MAP: dict[str, str] = {
    "plan_item_price": "subscription",
    "plan": "subscription",
    "plan_setup": "addon",
    "addon_item_price": "addon",
    "addon": "addon",
    "charge_item_price": "addon",
    "charge": "addon",
    "adhoc": "addon",
}

# Chargebee ``Transaction.payment_method`` → canonical payment-method
# type. "card" stays; bank methods bucket into ``direct_debit`` or
# ``bank_transfer``; wallets pool under ``wallet``; anything else falls
# through to ``other`` via the helper below.
_PAYMENT_METHOD_MAP: dict[str, str] = {
    "card": "card",
    "ideal": "card",
    "sofort": "card",
    "bancontact": "card",
    "paypal_express_checkout": "paypal",
    "amazon_payments": "wallet",
    "apple_pay": "wallet",
    "google_pay": "wallet",
    "ach_credit": "bank_transfer",
    "direct_debit": "direct_debit",
    "automated_bank_transfer": "bank_transfer",
}


def _canonical_payment_method(native: str | None) -> str | None:
    if native is None:
        return None
    return _PAYMENT_METHOD_MAP.get(native, "other")


def _canonical_status(native: str | None) -> str:
    if native is None:
        return "active"
    return _STATUS_MAP.get(native, native)


def _ts(unix_ts: int | None) -> str | None:
    if unix_ts is None:
        return None
    return datetime.fromtimestamp(unix_ts, tz=UTC).isoformat()


def _occurred_at(wh: dict[str, Any]) -> datetime:
    """Best-effort timestamp for the webhook event itself."""
    ts = wh.get("occurred_at") or wh.get("created_at")
    if ts:
        return datetime.fromtimestamp(int(ts), tz=UTC)
    return datetime.now(UTC)


# ── Catalog (item / item_price) serializers ──────────────────────────────


def _item_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "external_id": item["id"],
        "name": item.get("name") or item.get("external_name"),
        "description": item.get("description"),
        "active": item.get("status") == "active",
        "metadata": item.get("metadata") or {},
    }


def _item_price_payload(ip: dict[str, Any]) -> dict[str, Any]:
    period_unit = ip.get("period_unit") or "month"
    period = ip.get("period") or 1
    pricing_model = ip.get("pricing_model", "flat_fee")
    canonical_pricing = _PRICING_MODEL_MAP.get(pricing_model, "flat")
    # Chargebee Item Prices can be tied to either a "plan" Item (recurring)
    # or an "addon"/"charge" Item (one-off or metered). We only ingest
    # recurring item prices into the ``plan`` table; the connector caller
    # filters before calling this if needed.
    item_type = ip.get("item_type", "plan")
    usage_type = "metered" if item_type == "addon" and ip.get("metered") else "licensed"
    return {
        "external_id": ip["id"],
        "product_external_id": ip.get("item_id"),
        "name": ip.get("name") or ip.get("external_name"),
        "interval": _INTERVAL_MAP.get(period_unit, period_unit),
        "interval_count": int(period),
        "amount_cents": ip.get("price"),
        "currency": (ip.get("currency_code") or "").lower() or None,
        "pricing_model": canonical_pricing,
        "usage_type": usage_type,
        "trial_period_days": (
            ip.get("trial_period") if ip.get("trial_period_unit") == "day" else None
        ),
        "active": ip.get("status") == "active",
        "metadata": ip.get("metadata") or {},
    }


def _is_recurring_item_price(ip: dict[str, Any]) -> bool:
    """Recurring item_prices have a period + period_unit; one-off charges don't."""
    return bool(ip.get("period") and ip.get("period_unit"))


# ── Customer ─────────────────────────────────────────────────────────────


def _customer_payload(cust: dict[str, Any]) -> dict[str, Any]:
    billing_addr = cust.get("billing_address") or {}
    return {
        "external_id": cust["id"],
        "name": cust.get("first_name") or cust.get("company") or billing_addr.get("company"),
        "email": cust.get("email"),
        "currency": (cust.get("preferred_currency_code") or "").lower() or None,
        "country": billing_addr.get("country"),
        "metadata": cust.get("meta_data") or {},
    }


# ── Subscription ─────────────────────────────────────────────────────────


def _subscription_item_payload(it: dict[str, Any]) -> dict[str, Any]:
    """Project one Chargebee ``subscription_item`` row.

    Chargebee's ``amount`` on a subscription_item is the unit_price *
    quantity for the current period — for MRR purposes, the subscription's
    server-computed ``mrr`` is the source of truth, and we surface
    per-item ``mrr_cents=0`` for addons/charges (their contribution is
    folded into the subscription total). Plan items get the full amount
    so a per-plan breakdown sums correctly for single-plan subscriptions.
    """
    item_type = it.get("item_type", "plan")
    amount = it.get("amount") or 0
    item_mrr = amount if item_type == "plan" else 0
    return {
        "external_id": it.get("item_price_id") or "",
        "plan_external_id": it.get("item_price_id"),
        "quantity": it.get("quantity", 1) or 1,
        "mrr_cents": item_mrr,
        "metadata": it.get("metadata") or {},
    }


def _subscription_payload(sub: dict[str, Any]) -> dict[str, Any]:
    """Project a Chargebee subscription into the canonical payload.

    Notes on field mapping:
    - ``mrr_cents`` is taken straight from Chargebee's ``mrr`` field (the
      server-side computation). This is the documented MRR-override path.
    - ``status='non_renewing'`` collapses to canonical ``active`` plus
      ``pending_cancellation=True`` so dashboards still flag the future
      churn.
    - Chargebee's ``current_term_start/end`` map to current_period_*.
    """
    primary_item = (sub.get("subscription_items") or [{}])[0]
    plan_id = primary_item.get("item_price_id") or sub.get("plan_id") or ""
    quantity = primary_item.get("quantity", 1) or 1
    pending_cancellation = sub.get("status") == "non_renewing"
    return {
        "external_id": sub["id"],
        "customer_external_id": sub.get("customer_id"),
        "plan_external_id": plan_id,
        "status": _canonical_status(sub.get("status")),
        "mrr_cents": sub.get("mrr") or 0,
        "quantity": quantity,
        "currency": (sub.get("currency_code") or "").lower() or None,
        "started_at": _ts(sub.get("started_at")),
        "trial_start": _ts(sub.get("trial_start")),
        "trial_end": _ts(sub.get("trial_end")),
        "current_period_start": _ts(sub.get("current_term_start")),
        "current_period_end": _ts(sub.get("current_term_end")),
        "pending_cancellation": pending_cancellation,
        "items": [_subscription_item_payload(it) for it in (sub.get("subscription_items") or [])],
    }


# ── Invoice ──────────────────────────────────────────────────────────────


# Chargebee ``Invoice.status`` → canonical.
_INVOICE_STATUS_MAP: dict[str, str] = {
    "pending": "draft",
    "posted": "draft",
    "payment_due": "open",
    "not_paid": "open",
    "paid": "paid",
    "voided": "void",
}


def _classify_invoice_line(li: dict[str, Any]) -> str:
    """Map a Chargebee invoice line to a canonical kind."""
    entity_type = li.get("entity_type") or ""
    # Discounts come through as separate ``discounts`` blocks on the
    # invoice header in Chargebee; line-item negatives are credits.
    if li.get("is_proration"):
        return "proration"
    if li.get("tax_amount") and not li.get("amount"):
        return "tax"
    return _LINE_ENTITY_MAP.get(entity_type, "other")


def _invoice_line_payload(li: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": li.get("entity_type"),
        "kind": _classify_invoice_line(li),
        "description": li.get("description"),
        "amount_cents": li.get("amount", 0),
        "currency": None,  # filled in by invoice currency at state layer
        "quantity": li.get("quantity"),
        "period_start": _ts(li.get("date_from")),
        "period_end": _ts(li.get("date_to")),
        "subscription_external_id": li.get("subscription_id"),
        "price_external_id": li.get("entity_id"),
        "coupon_external_id": None,
        "credit_note_external_id": None,
    }


def _invoice_payload(inv: dict[str, Any]) -> dict[str, Any]:
    status = _INVOICE_STATUS_MAP.get(inv.get("status") or "", inv.get("status"))
    return {
        "external_id": inv["id"],
        "customer_external_id": inv.get("customer_id"),
        "subscription_external_id": inv.get("subscription_id"),
        "status": status,
        "currency": (inv.get("currency_code") or "").lower() or None,
        "subtotal_cents": inv.get("sub_total", 0) or 0,
        "tax_cents": inv.get("tax", 0) or 0,
        "total_cents": inv.get("total", 0) or 0,
        "period_start": _ts(inv.get("start_date")),
        "period_end": _ts(inv.get("end_date")),
        "line_items": [_invoice_line_payload(li) for li in (inv.get("line_items") or [])],
    }


# ── Payment (Chargebee Transaction) ──────────────────────────────────────


def _transaction_payload(txn: dict[str, Any]) -> dict[str, Any]:
    return {
        "external_id": txn["id"],
        "invoice_external_id": _txn_invoice_id(txn),
        "customer_external_id": txn.get("customer_id"),
        "amount_cents": txn.get("amount", 0) or 0,
        "currency": (txn.get("currency_code") or "").lower() or None,
        "payment_method_type": _canonical_payment_method(txn.get("payment_method")),
    }


def _txn_invoice_id(txn: dict[str, Any]) -> str | None:
    """Pull the first linked invoice ID out of a Transaction's ``linked_invoices``."""
    linked = txn.get("linked_invoices") or []
    if not linked:
        return None
    invoice_id = linked[0].get("invoice_id")
    if invoice_id is None:
        return None
    return str(invoice_id)


# ── Coupon ───────────────────────────────────────────────────────────────


# Chargebee ``Coupon.duration_type`` → canonical coupon duration.
_COUPON_DURATION_MAP: dict[str, str] = {
    "forever": "forever",
    "one_time": "once",
    "limited_period": "repeating",
}


def _coupon_payload(c: dict[str, Any]) -> dict[str, Any]:
    duration_type = c.get("duration_type") or "one_time"
    duration_in_months = None
    if duration_type == "limited_period" and c.get("period_unit") == "month":
        duration_in_months = c.get("period")
    return {
        "external_id": c["id"],
        "code": c.get("id"),
        "name": c.get("name"),
        "percent_off": c.get("discount_percentage"),
        "amount_off_cents": c.get("discount_amount"),
        "currency": (c.get("currency_code") or "").lower() or None,
        "duration": _COUPON_DURATION_MAP.get(duration_type, "once"),
        "duration_in_months": duration_in_months,
        "max_redemptions": c.get("max_redemptions"),
        "times_redeemed": c.get("redemptions") or 0,
        "valid": c.get("status") == "active",
        "redeem_by": _ts(c.get("valid_till")),
        "metadata": c.get("meta_data") or {},
    }


# ── Credit Note ──────────────────────────────────────────────────────────


# Chargebee ``CreditNote.status`` → canonical.
_CREDIT_NOTE_STATUS_MAP: dict[str, str] = {
    "adjusted": "issued",
    "refunded": "issued",
    "refund_due": "issued",
    "voided": "void",
}

# Chargebee ``CreditNote.reason_code`` → canonical reason. Anything Chargebee
# specific (e.g. ``write_off``, ``chargeback``) collapses to ``other``.
_CREDIT_NOTE_REASON_MAP: dict[str, str] = {
    "duplicate": "duplicate",
    "fraudulent": "fraudulent",
    "order_change": "order_change",
    "cancellation": "order_change",
    "product_unsatisfactory": "product_unsatisfactory",
    "service_unsatisfactory": "product_unsatisfactory",
}


def _credit_note_payload(cn: dict[str, Any]) -> dict[str, Any]:
    status = _CREDIT_NOTE_STATUS_MAP.get(cn.get("status") or "", "issued")
    raw_reason = cn.get("reason_code")
    reason = _CREDIT_NOTE_REASON_MAP.get(raw_reason or "", "other") if raw_reason else None
    return {
        "external_id": cn["id"],
        "invoice_external_id": cn.get("reference_invoice_id"),
        "customer_external_id": cn.get("customer_id"),
        "status": status,
        "reason": reason,
        "currency": (cn.get("currency_code") or "").lower() or None,
        "subtotal_cents": cn.get("sub_total", 0) or 0,
        "tax_cents": cn.get("total_tax", 0) or 0,
        "total_cents": cn.get("total", 0) or 0,
        "memo": cn.get("description"),
        "issued_at": _ts(cn.get("date") or cn.get("created_at")),
        "metadata": cn.get("meta_data") or {},
    }


# ── Connector ────────────────────────────────────────────────────────────


@register("chargebee")
class ChargebeeConnector(WebhookConnector):
    """Chargebee webhook translator + signature verifier."""

    @property
    def source_type(self) -> str:
        return "chargebee"

    @classmethod
    def router(cls) -> APIRouter:
        from tidemill.connectors.chargebee.routes import router

        return router

    # ── translate ────────────────────────────────────────────────────────

    _HANDLERS: dict[str, str] = {
        "customer_created": "_translate_customer_created",
        "customer_changed": "_translate_customer_updated",
        "customer_deleted": "_translate_customer_deleted",
        "item_created": "_translate_item_created",
        "item_updated": "_translate_item_updated",
        "item_deleted": "_translate_item_deleted",
        "item_price_created": "_translate_item_price_created",
        "item_price_updated": "_translate_item_price_updated",
        "item_price_deleted": "_translate_item_price_deleted",
        "subscription_created": "_translate_subscription_created",
        "subscription_started": "_translate_subscription_activated",
        "subscription_activated": "_translate_subscription_activated",
        "subscription_changed": "_translate_subscription_changed",
        "subscription_cancelled": "_translate_subscription_cancelled",
        "subscription_paused": "_translate_subscription_paused",
        "subscription_resumed": "_translate_subscription_resumed",
        "subscription_reactivated": "_translate_subscription_activated",
        "subscription_renewed": "_translate_subscription_changed",
        "subscription_deleted": "_translate_subscription_deleted",
        "invoice_generated": "_translate_invoice_created",
        "invoice_updated": "_translate_invoice_updated",
        "payment_succeeded": "_translate_payment_succeeded",
        "payment_failed": "_translate_payment_failed",
        "payment_refunded": "_translate_payment_refunded",
        "coupon_created": "_translate_coupon_created",
        "coupon_updated": "_translate_coupon_updated",
        "coupon_deleted": "_translate_coupon_deleted",
        "credit_note_created": "_translate_credit_note_created",
        "credit_note_updated": "_translate_credit_note_updated",
        "credit_note_deleted": "_translate_credit_note_voided",
    }

    def translate(self, webhook_payload: dict[str, Any]) -> list[Event]:
        event_type = webhook_payload.get("event_type", "")
        handler_name = self._HANDLERS.get(event_type)
        if handler_name is None:
            return []
        handler: Callable[..., list[Event]] = getattr(self, handler_name)
        return handler(webhook_payload)

    # ── verify_signature ─────────────────────────────────────────────────

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """Validate the Chargebee Basic Auth credential.

        Chargebee posts webhooks with HTTP Basic Auth — the *signature*
        argument here is the raw ``Authorization`` header value
        (``Basic base64(user:pass)``). We decode, compare against the
        configured CHARGEBEE_WEBHOOK_USERNAME / CHARGEBEE_WEBHOOK_PASSWORD,
        and use ``hmac.compare_digest`` to avoid timing leaks.

        When neither username nor password is configured we fall back to
        ``return True`` (matches the Stripe / QuickBooks lenient default
        for local dev). Production deployments must configure both.
        """
        expected_user = (self.config.get("webhook_username") or "").strip()
        expected_pass = self.config.get("webhook_password") or ""
        if not expected_user and not expected_pass:
            return True
        if not signature.lower().startswith("basic "):
            return False
        try:
            decoded = base64.b64decode(signature.split(" ", 1)[1]).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return False
        user, _, password = decoded.partition(":")
        return hmac.compare_digest(user, expected_user) and hmac.compare_digest(
            password, expected_pass
        )

    # ── event factory ────────────────────────────────────────────────────

    def _make_event(
        self,
        event_type: str,
        *,
        customer_id: str,
        external_id: str,
        occurred_at: datetime,
        payload: dict[str, Any],
    ) -> Event:
        return Event(
            id=make_event_id(self.source_id, event_type, external_id),
            source_id=self.source_id,
            type=event_type,
            occurred_at=occurred_at,
            published_at=datetime.now(UTC),
            customer_id=customer_id,
            payload=payload,
        )

    @staticmethod
    def _content(wh: dict[str, Any]) -> dict[str, Any]:
        return wh.get("content") or {}

    # ── customer handlers ────────────────────────────────────────────────

    def _translate_customer_created(self, wh: dict[str, Any]) -> list[Event]:
        cust = self._content(wh).get("customer") or {}
        return [
            self._make_event(
                "customer.created",
                customer_id=cust.get("id", ""),
                external_id=cust.get("id", ""),
                occurred_at=_occurred_at(wh),
                payload=_customer_payload(cust),
            )
        ]

    def _translate_customer_updated(self, wh: dict[str, Any]) -> list[Event]:
        cust = self._content(wh).get("customer") or {}
        return [
            self._make_event(
                "customer.updated",
                customer_id=cust.get("id", ""),
                external_id=cust.get("id", ""),
                occurred_at=_occurred_at(wh),
                payload=_customer_payload(cust),
            )
        ]

    def _translate_customer_deleted(self, wh: dict[str, Any]) -> list[Event]:
        cust = self._content(wh).get("customer") or {}
        ext_id = cust.get("id", "")
        return [
            self._make_event(
                "customer.deleted",
                customer_id=ext_id,
                external_id=ext_id,
                occurred_at=_occurred_at(wh),
                payload={"external_id": ext_id},
            )
        ]

    # ── catalog handlers ─────────────────────────────────────────────────

    def _translate_item_created(self, wh: dict[str, Any]) -> list[Event]:
        item = self._content(wh).get("item") or {}
        return [
            self._make_event(
                "product.created",
                customer_id="",
                external_id=item.get("id", ""),
                occurred_at=_occurred_at(wh),
                payload=_item_payload(item),
            )
        ]

    def _translate_item_updated(self, wh: dict[str, Any]) -> list[Event]:
        item = self._content(wh).get("item") or {}
        return [
            self._make_event(
                "product.updated",
                customer_id="",
                external_id=item.get("id", ""),
                occurred_at=_occurred_at(wh),
                payload=_item_payload(item),
            )
        ]

    def _translate_item_deleted(self, wh: dict[str, Any]) -> list[Event]:
        item = self._content(wh).get("item") or {}
        ext_id = item.get("id", "")
        return [
            self._make_event(
                "product.deleted",
                customer_id="",
                external_id=ext_id,
                occurred_at=_occurred_at(wh),
                payload={"external_id": ext_id},
            )
        ]

    def _translate_item_price_created(self, wh: dict[str, Any]) -> list[Event]:
        ip = self._content(wh).get("item_price") or {}
        if not _is_recurring_item_price(ip):
            return []
        return [
            self._make_event(
                "plan.created",
                customer_id="",
                external_id=ip.get("id", ""),
                occurred_at=_occurred_at(wh),
                payload=_item_price_payload(ip),
            )
        ]

    def _translate_item_price_updated(self, wh: dict[str, Any]) -> list[Event]:
        ip = self._content(wh).get("item_price") or {}
        if not _is_recurring_item_price(ip):
            return []
        return [
            self._make_event(
                "plan.updated",
                customer_id="",
                external_id=ip.get("id", ""),
                occurred_at=_occurred_at(wh),
                payload=_item_price_payload(ip),
            )
        ]

    def _translate_item_price_deleted(self, wh: dict[str, Any]) -> list[Event]:
        ip = self._content(wh).get("item_price") or {}
        ext_id = ip.get("id", "")
        return [
            self._make_event(
                "plan.deleted",
                customer_id="",
                external_id=ext_id,
                occurred_at=_occurred_at(wh),
                payload={"external_id": ext_id},
            )
        ]

    # ── subscription handlers ────────────────────────────────────────────

    def _translate_subscription_created(self, wh: dict[str, Any]) -> list[Event]:
        sub = self._content(wh).get("subscription") or {}
        cust_id = sub.get("customer_id", "")
        events: list[Event] = [
            self._make_event(
                "subscription.created",
                customer_id=cust_id,
                external_id=sub.get("id", ""),
                occurred_at=_occurred_at(wh),
                payload=_subscription_payload(sub),
            )
        ]
        status = sub.get("status")
        if status == "in_trial":
            events.append(
                self._make_event(
                    "subscription.trial_started",
                    customer_id=cust_id,
                    external_id=sub.get("id", ""),
                    occurred_at=_occurred_at(wh),
                    payload={
                        "external_id": sub.get("id"),
                        "trial_start": _ts(sub.get("trial_start")),
                        "trial_end": _ts(sub.get("trial_end")),
                    },
                )
            )
        elif status == "active":
            events.append(
                self._make_event(
                    "subscription.activated",
                    customer_id=cust_id,
                    external_id=sub.get("id", ""),
                    occurred_at=_occurred_at(wh),
                    payload={
                        "external_id": sub.get("id"),
                        "mrr_cents": sub.get("mrr") or 0,
                        "currency": (sub.get("currency_code") or "").lower() or None,
                    },
                )
            )
        return events

    def _translate_subscription_activated(self, wh: dict[str, Any]) -> list[Event]:
        sub = self._content(wh).get("subscription") or {}
        cust_id = sub.get("customer_id", "")
        prior = self._content(wh).get("prior_subscription") or {}
        events: list[Event] = []
        if prior.get("status") == "in_trial" and sub.get("status") == "active":
            events.append(
                self._make_event(
                    "subscription.trial_converted",
                    customer_id=cust_id,
                    external_id=sub.get("id", ""),
                    occurred_at=_occurred_at(wh),
                    payload={
                        "external_id": sub.get("id"),
                        "mrr_cents": sub.get("mrr") or 0,
                        "currency": (sub.get("currency_code") or "").lower() or None,
                    },
                )
            )
        events.append(
            self._make_event(
                "subscription.activated",
                customer_id=cust_id,
                external_id=sub.get("id", ""),
                occurred_at=_occurred_at(wh),
                payload={
                    "external_id": sub.get("id"),
                    "mrr_cents": sub.get("mrr") or 0,
                    "currency": (sub.get("currency_code") or "").lower() or None,
                },
            )
        )
        return events

    def _translate_subscription_changed(self, wh: dict[str, Any]) -> list[Event]:
        sub = self._content(wh).get("subscription") or {}
        prior = self._content(wh).get("prior_subscription") or {}
        cust_id = sub.get("customer_id", "")
        new_mrr = sub.get("mrr") or 0
        prev_mrr = prior.get("mrr") or 0
        # Skip MRR-neutral updates (period rotation, address change,
        # etc.) — they're noise for the metric layer, which derives
        # movement from MRR deltas.
        if new_mrr == prev_mrr:
            return []
        return [
            self._make_event(
                "subscription.changed",
                customer_id=cust_id,
                external_id=sub.get("id", ""),
                occurred_at=_occurred_at(wh),
                payload={
                    "external_id": sub.get("id"),
                    "prev_plan_external_id": (
                        (prior.get("subscription_items") or [{}])[0].get("item_price_id")
                        if prior
                        else None
                    ),
                    "new_plan_external_id": (
                        (sub.get("subscription_items") or [{}])[0].get("item_price_id")
                    ),
                    "prev_mrr_cents": prev_mrr,
                    "new_mrr_cents": new_mrr,
                    "prev_quantity": (
                        (prior.get("subscription_items") or [{}])[0].get("quantity", 1)
                        if prior
                        else 1
                    ),
                    "new_quantity": (sub.get("subscription_items") or [{}])[0].get("quantity", 1),
                    "currency": (sub.get("currency_code") or "").lower() or None,
                    "items": [
                        _subscription_item_payload(it)
                        for it in (sub.get("subscription_items") or [])
                    ],
                },
            )
        ]

    def _translate_subscription_cancelled(self, wh: dict[str, Any]) -> list[Event]:
        sub = self._content(wh).get("subscription") or {}
        cust_id = sub.get("customer_id", "")
        # Chargebee's ``subscription_cancelled`` fires once cancellation
        # takes effect (status='cancelled'). If the user only scheduled
        # cancellation (non_renewing), Chargebee fires
        # ``subscription_changed`` with status='non_renewing' instead —
        # the connector flags ``pending_cancellation`` there via the
        # subscription_payload mapping.
        return [
            self._make_event(
                "subscription.canceled",
                customer_id=cust_id,
                external_id=sub.get("id", ""),
                occurred_at=_occurred_at(wh),
                payload={
                    "external_id": sub.get("id"),
                    "mrr_cents": sub.get("mrr") or 0,
                    "currency": (sub.get("currency_code") or "").lower() or None,
                    "canceled_at": _ts(sub.get("cancelled_at")),
                    "cancel_reason": sub.get("cancel_reason"),
                    "cancel_feedback": None,
                },
            )
        ]

    def _translate_subscription_paused(self, wh: dict[str, Any]) -> list[Event]:
        sub = self._content(wh).get("subscription") or {}
        cust_id = sub.get("customer_id", "")
        return [
            self._make_event(
                "subscription.paused",
                customer_id=cust_id,
                external_id=sub.get("id", ""),
                occurred_at=_occurred_at(wh),
                payload={
                    "external_id": sub.get("id"),
                    "mrr_cents": sub.get("mrr") or 0,
                    "currency": (sub.get("currency_code") or "").lower() or None,
                },
            )
        ]

    def _translate_subscription_resumed(self, wh: dict[str, Any]) -> list[Event]:
        sub = self._content(wh).get("subscription") or {}
        cust_id = sub.get("customer_id", "")
        return [
            self._make_event(
                "subscription.resumed",
                customer_id=cust_id,
                external_id=sub.get("id", ""),
                occurred_at=_occurred_at(wh),
                payload={
                    "external_id": sub.get("id"),
                    "mrr_cents": sub.get("mrr") or 0,
                    "currency": (sub.get("currency_code") or "").lower() or None,
                },
            )
        ]

    def _translate_subscription_deleted(self, wh: dict[str, Any]) -> list[Event]:
        sub = self._content(wh).get("subscription") or {}
        cust_id = sub.get("customer_id", "")
        return [
            self._make_event(
                "subscription.churned",
                customer_id=cust_id,
                external_id=sub.get("id", ""),
                occurred_at=_occurred_at(wh),
                payload={
                    "external_id": sub.get("id"),
                    "prev_mrr_cents": sub.get("mrr") or 0,
                    "currency": (sub.get("currency_code") or "").lower() or None,
                    "cancel_reason": sub.get("cancel_reason"),
                    "cancel_feedback": None,
                },
            )
        ]

    # ── invoice handlers ─────────────────────────────────────────────────

    def _translate_invoice_created(self, wh: dict[str, Any]) -> list[Event]:
        inv = self._content(wh).get("invoice") or {}
        events: list[Event] = [
            self._make_event(
                "invoice.created",
                customer_id=inv.get("customer_id", ""),
                external_id=inv.get("id", ""),
                occurred_at=_occurred_at(wh),
                payload=_invoice_payload(inv),
            )
        ]
        if inv.get("status") == "paid":
            events.append(
                self._make_event(
                    "invoice.paid",
                    customer_id=inv.get("customer_id", ""),
                    external_id=inv.get("id", ""),
                    occurred_at=_occurred_at(wh),
                    payload={
                        "external_id": inv.get("id"),
                        "subscription_external_id": inv.get("subscription_id"),
                        "paid_at": _ts(inv.get("paid_at")),
                        "amount_cents": inv.get("amount_paid", 0) or 0,
                        "currency": (inv.get("currency_code") or "").lower() or None,
                    },
                )
            )
        return events

    def _translate_invoice_updated(self, wh: dict[str, Any]) -> list[Event]:
        inv = self._content(wh).get("invoice") or {}
        status = inv.get("status")
        events: list[Event] = []
        if status == "paid":
            events.append(
                self._make_event(
                    "invoice.paid",
                    customer_id=inv.get("customer_id", ""),
                    external_id=inv.get("id", ""),
                    occurred_at=_occurred_at(wh),
                    payload={
                        "external_id": inv.get("id"),
                        "subscription_external_id": inv.get("subscription_id"),
                        "paid_at": _ts(inv.get("paid_at")),
                        "amount_cents": inv.get("amount_paid", 0) or 0,
                        "currency": (inv.get("currency_code") or "").lower() or None,
                    },
                )
            )
        elif status == "voided":
            events.append(
                self._make_event(
                    "invoice.voided",
                    customer_id=inv.get("customer_id", ""),
                    external_id=inv.get("id", ""),
                    occurred_at=_occurred_at(wh),
                    payload={
                        "external_id": inv.get("id"),
                        "voided_at": _ts(inv.get("voided_at")),
                    },
                )
            )
        return events

    # ── payment / transaction handlers ───────────────────────────────────

    def _translate_payment_succeeded(self, wh: dict[str, Any]) -> list[Event]:
        txn = self._content(wh).get("transaction") or {}
        return [
            self._make_event(
                "payment.succeeded",
                customer_id=txn.get("customer_id", ""),
                external_id=txn.get("id", ""),
                occurred_at=_occurred_at(wh),
                payload=_transaction_payload(txn),
            )
        ]

    def _translate_payment_failed(self, wh: dict[str, Any]) -> list[Event]:
        txn = self._content(wh).get("transaction") or {}
        payload = _transaction_payload(txn)
        payload["failure_reason"] = txn.get("error_text") or txn.get("error_code")
        payload["attempt_count"] = txn.get("dunning_attempts")
        return [
            self._make_event(
                "payment.failed",
                customer_id=txn.get("customer_id", ""),
                external_id=txn.get("id", ""),
                occurred_at=_occurred_at(wh),
                payload=payload,
            )
        ]

    def _translate_payment_refunded(self, wh: dict[str, Any]) -> list[Event]:
        txn = self._content(wh).get("transaction") or {}
        # Refunds in Chargebee are separate Transactions with
        # ``type=refund``; the original txn ID is in
        # ``reference_transaction_id``. The canonical event mirrors the
        # original transaction's external_id so state.payment refunds the
        # existing row instead of inserting a duplicate.
        original = txn.get("reference_transaction_id") or txn.get("id", "")
        return [
            self._make_event(
                "payment.refunded",
                customer_id=txn.get("customer_id", ""),
                external_id=original,
                occurred_at=_occurred_at(wh),
                payload={
                    "external_id": original,
                    "amount_cents": txn.get("amount", 0) or 0,
                    "refunded_at": _ts(txn.get("date") or txn.get("created_at")),
                },
            )
        ]

    # ── coupon handlers ──────────────────────────────────────────────────

    def _translate_coupon_created(self, wh: dict[str, Any]) -> list[Event]:
        c = self._content(wh).get("coupon") or {}
        return [
            self._make_event(
                "coupon.created",
                customer_id="",
                external_id=c.get("id", ""),
                occurred_at=_occurred_at(wh),
                payload=_coupon_payload(c),
            )
        ]

    def _translate_coupon_updated(self, wh: dict[str, Any]) -> list[Event]:
        c = self._content(wh).get("coupon") or {}
        return [
            self._make_event(
                "coupon.updated",
                customer_id="",
                external_id=c.get("id", ""),
                occurred_at=_occurred_at(wh),
                payload=_coupon_payload(c),
            )
        ]

    def _translate_coupon_deleted(self, wh: dict[str, Any]) -> list[Event]:
        c = self._content(wh).get("coupon") or {}
        ext_id = c.get("id", "")
        return [
            self._make_event(
                "coupon.deleted",
                customer_id="",
                external_id=ext_id,
                occurred_at=_occurred_at(wh),
                payload={"external_id": ext_id},
            )
        ]

    # ── credit_note handlers ─────────────────────────────────────────────

    def _translate_credit_note_created(self, wh: dict[str, Any]) -> list[Event]:
        cn = self._content(wh).get("credit_note") or {}
        return [
            self._make_event(
                "credit_note.created",
                customer_id=cn.get("customer_id", ""),
                external_id=cn.get("id", ""),
                occurred_at=_occurred_at(wh),
                payload=_credit_note_payload(cn),
            )
        ]

    def _translate_credit_note_updated(self, wh: dict[str, Any]) -> list[Event]:
        cn = self._content(wh).get("credit_note") or {}
        # An update that flips status → voided emits the canonical voided
        # event; other updates re-emit credit_note.created so the state
        # upsert refreshes totals/memo.
        if cn.get("status") == "voided":
            return [
                self._make_event(
                    "credit_note.voided",
                    customer_id=cn.get("customer_id", ""),
                    external_id=cn.get("id", ""),
                    occurred_at=_occurred_at(wh),
                    payload={
                        "external_id": cn.get("id"),
                        "voided_at": _ts(cn.get("voided_at")),
                    },
                )
            ]
        return [
            self._make_event(
                "credit_note.created",
                customer_id=cn.get("customer_id", ""),
                external_id=cn.get("id", ""),
                occurred_at=_occurred_at(wh),
                payload=_credit_note_payload(cn),
            )
        ]

    def _translate_credit_note_voided(self, wh: dict[str, Any]) -> list[Event]:
        cn = self._content(wh).get("credit_note") or {}
        return [
            self._make_event(
                "credit_note.voided",
                customer_id=cn.get("customer_id", ""),
                external_id=cn.get("id", ""),
                occurred_at=_occurred_at(wh),
                payload={
                    "external_id": cn.get("id"),
                    "voided_at": _ts(cn.get("voided_at") or cn.get("updated_at")),
                },
            )
        ]

    # ── backfill ─────────────────────────────────────────────────────────

    async def backfill(  # pragma: no cover
        self, since: datetime | None = None
    ) -> AsyncIterator[Event]:
        """Backfill historical data from the Chargebee site.

        Stub: full backfill via the Chargebee List APIs is tracked
        separately. For now, replay webhooks (or re-run the seed) to
        populate Tidemill from Chargebee.
        """
        raise NotImplementedError(
            "Chargebee backfill is not implemented yet — use webhook replay or "
            "re-run deploy/seed/chargebee_seed.py."
        )
        yield  # noqa: RET503 — unreachable yield makes this an async generator
