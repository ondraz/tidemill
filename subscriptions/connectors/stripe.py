"""Stripe webhook connector — reference implementation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import stripe

from subscriptions.connectors.base import WebhookConnector
from subscriptions.connectors.registry import register
from subscriptions.events import Event, make_event_id

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable


def _ts(unix_ts: int | None) -> str | None:
    """Convert a Unix timestamp to ISO 8601, or *None*."""
    if unix_ts is None:
        return None
    return datetime.fromtimestamp(unix_ts, tz=UTC).isoformat()


@register("stripe")
class StripeConnector(WebhookConnector):
    """Stripe webhook translator, signature verifier, and backfill generator."""

    @property
    def source_type(self) -> str:
        return "stripe"

    # ── translate ────────────────────────────────────────────────────────

    _HANDLERS: dict[str, str] = {
        "customer.created": "_translate_customer_created",
        "customer.updated": "_translate_customer_updated",
        "customer.deleted": "_translate_customer_deleted",
        "customer.subscription.created": "_translate_subscription_created",
        "customer.subscription.updated": "_translate_subscription_updated",
        "customer.subscription.deleted": "_translate_subscription_deleted",
        "invoice.created": "_translate_invoice_created",
        "invoice.paid": "_translate_invoice_paid",
        "invoice.voided": "_translate_invoice_voided",
        "invoice.marked_uncollectible": "_translate_invoice_uncollectible",
        "payment_intent.succeeded": "_translate_payment_succeeded",
        "payment_intent.payment_failed": "_translate_payment_failed",
        "charge.refunded": "_translate_charge_refunded",
    }

    def translate(self, webhook_payload: dict[str, Any]) -> list[Event]:
        event_type = webhook_payload.get("type", "")
        handler_name = self._HANDLERS.get(event_type)
        if handler_name is None:
            return []
        handler: Callable[..., list[Event]] = getattr(self, handler_name)
        return handler(webhook_payload)

    # ── verify_signature ─────────────────────────────────────────────────

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        secret = self.config.get("webhook_secret")
        if not secret:
            return True
        try:
            stripe.Webhook.construct_event(payload, signature, secret)  # type: ignore[no-untyped-call]
            return True
        except stripe.SignatureVerificationError:
            return False

    # ── MRR computation ──────────────────────────────────────────────────

    @staticmethod
    def _compute_mrr(subscription: dict[str, Any]) -> int:
        """Compute monthly MRR in cents from a Stripe subscription object."""
        total = 0
        items = subscription.get("items", {})
        items_data = items.get("data", []) if isinstance(items, dict) else []
        for item in items_data:
            price = item.get("price", {})
            qty = item.get("quantity", 1) or 1
            unit_amount = price.get("unit_amount", 0) or 0
            amount = unit_amount * qty
            recurring = price.get("recurring") or {}
            interval = recurring.get("interval", "month")
            interval_count = recurring.get("interval_count", 1) or 1

            match interval:
                case "month":
                    total += amount // interval_count
                case "year":
                    total += amount // (12 * interval_count)
                case "week":
                    total += int(amount * 52 / (12 * interval_count))
                case "day":
                    total += int(amount * 365 / (12 * interval_count))
        return total

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

    def _occurred(self, obj: dict[str, Any]) -> datetime:
        """Best-effort occurred_at from a Stripe object."""
        ts = obj.get("created")
        if ts:
            return datetime.fromtimestamp(ts, tz=UTC)
        return datetime.now(UTC)

    # ── customer handlers ────────────────────────────────────────────────

    def _translate_customer_created(self, wh: dict[str, Any]) -> list[Event]:
        cust = wh["data"]["object"]
        return [
            self._make_event(
                "customer.created",
                customer_id=cust["id"],
                external_id=cust["id"],
                occurred_at=self._occurred(cust),
                payload={
                    "external_id": cust["id"],
                    "name": cust.get("name"),
                    "email": cust.get("email"),
                    "currency": cust.get("currency"),
                    "metadata": cust.get("metadata", {}),
                },
            )
        ]

    def _translate_customer_updated(self, wh: dict[str, Any]) -> list[Event]:
        cust = wh["data"]["object"]
        prev = wh["data"].get("previous_attributes", {})
        return [
            self._make_event(
                "customer.updated",
                customer_id=cust["id"],
                external_id=cust["id"],
                occurred_at=self._occurred(cust),
                payload={
                    "external_id": cust["id"],
                    "changed_fields": prev,
                },
            )
        ]

    def _translate_customer_deleted(self, wh: dict[str, Any]) -> list[Event]:
        cust = wh["data"]["object"]
        return [
            self._make_event(
                "customer.deleted",
                customer_id=cust["id"],
                external_id=cust["id"],
                occurred_at=self._occurred(cust),
                payload={"external_id": cust["id"]},
            )
        ]

    # ── subscription handlers ────────────────────────────────────────────

    def _translate_subscription_created(self, wh: dict[str, Any]) -> list[Event]:
        sub = wh["data"]["object"]
        cust_id = sub["customer"]
        events: list[Event] = []

        events.append(
            self._make_event(
                "subscription.created",
                customer_id=cust_id,
                external_id=sub["id"],
                occurred_at=self._occurred(sub),
                payload={
                    "external_id": sub["id"],
                    "customer_external_id": cust_id,
                    "plan_external_id": self._plan_id(sub),
                    "status": sub["status"],
                    "mrr_cents": self._compute_mrr(sub),
                    "quantity": self._total_quantity(sub),
                    "currency": sub.get("currency"),
                    "started_at": _ts(sub.get("start_date")),
                    "trial_start": _ts(sub.get("trial_start")),
                    "trial_end": _ts(sub.get("trial_end")),
                    "current_period_start": _ts(sub.get("current_period_start")),
                    "current_period_end": _ts(sub.get("current_period_end")),
                },
            )
        )

        if sub.get("status") == "trialing":
            events.append(
                self._make_event(
                    "subscription.trial_started",
                    customer_id=cust_id,
                    external_id=sub["id"],
                    occurred_at=self._occurred(sub),
                    payload={
                        "external_id": sub["id"],
                        "trial_start": _ts(sub.get("trial_start")),
                        "trial_end": _ts(sub.get("trial_end")),
                    },
                )
            )

        return events

    def _translate_subscription_updated(self, wh: dict[str, Any]) -> list[Event]:
        sub = wh["data"]["object"]
        prev = wh["data"].get("previous_attributes", {})
        cust_id = sub["customer"]
        events: list[Event] = []
        mrr = self._compute_mrr(sub)

        # Status transitions
        if "status" in prev:
            old_status = prev["status"]
            new_status = sub["status"]

            if old_status == "trialing" and new_status == "active":
                events.append(
                    self._make_event(
                        "subscription.trial_converted",
                        customer_id=cust_id,
                        external_id=sub["id"],
                        occurred_at=self._occurred(sub),
                        payload={"external_id": sub["id"], "mrr_cents": mrr},
                    )
                )
                events.append(
                    self._make_event(
                        "subscription.activated",
                        customer_id=cust_id,
                        external_id=sub["id"],
                        occurred_at=self._occurred(sub),
                        payload={"external_id": sub["id"], "mrr_cents": mrr},
                    )
                )
            elif old_status == "trialing" and new_status in ("canceled", "unpaid"):
                events.append(
                    self._make_event(
                        "subscription.trial_expired",
                        customer_id=cust_id,
                        external_id=sub["id"],
                        occurred_at=self._occurred(sub),
                        payload={"external_id": sub["id"]},
                    )
                )
            elif new_status == "active" and old_status != "active":
                events.append(
                    self._make_event(
                        "subscription.activated",
                        customer_id=cust_id,
                        external_id=sub["id"],
                        occurred_at=self._occurred(sub),
                        payload={"external_id": sub["id"], "mrr_cents": mrr},
                    )
                )
            elif new_status == "canceled":
                events.append(
                    self._make_event(
                        "subscription.canceled",
                        customer_id=cust_id,
                        external_id=sub["id"],
                        occurred_at=self._occurred(sub),
                        payload={
                            "external_id": sub["id"],
                            "mrr_cents": mrr,
                            "canceled_at": _ts(sub.get("canceled_at")),
                            "ends_at": _ts(sub.get("current_period_end")),
                        },
                    )
                )
            elif new_status == "paused":
                events.append(
                    self._make_event(
                        "subscription.paused",
                        customer_id=cust_id,
                        external_id=sub["id"],
                        occurred_at=self._occurred(sub),
                        payload={"external_id": sub["id"], "mrr_cents": mrr},
                    )
                )

        # Resume from pause
        if "pause_collection" in prev and sub.get("pause_collection") is None:
            events.append(
                self._make_event(
                    "subscription.resumed",
                    customer_id=cust_id,
                    external_id=sub["id"],
                    occurred_at=self._occurred(sub),
                    payload={"external_id": sub["id"], "mrr_cents": mrr},
                )
            )

        # Pending cancellation
        if "cancel_at_period_end" in prev and sub.get("cancel_at_period_end"):
            events.append(
                self._make_event(
                    "subscription.canceled",
                    customer_id=cust_id,
                    external_id=sub["id"],
                    occurred_at=self._occurred(sub),
                    payload={
                        "external_id": sub["id"],
                        "mrr_cents": mrr,
                        "canceled_at": _ts(sub.get("canceled_at")),
                        "ends_at": _ts(sub.get("current_period_end")),
                    },
                )
            )

        # Plan or quantity change
        if "items" in prev or "quantity" in prev:
            prev_sub = {**sub, **prev}
            prev_mrr = self._compute_mrr(prev_sub)
            new_mrr = mrr
            if prev_mrr != new_mrr:
                events.append(
                    self._make_event(
                        "subscription.changed",
                        customer_id=cust_id,
                        external_id=sub["id"],
                        occurred_at=self._occurred(sub),
                        payload={
                            "external_id": sub["id"],
                            "prev_plan_external_id": self._plan_id(prev_sub),
                            "new_plan_external_id": self._plan_id(sub),
                            "prev_mrr_cents": prev_mrr,
                            "new_mrr_cents": new_mrr,
                            "prev_quantity": self._total_quantity(prev_sub),
                            "new_quantity": self._total_quantity(sub),
                        },
                    )
                )

        return events

    def _translate_subscription_deleted(self, wh: dict[str, Any]) -> list[Event]:
        sub = wh["data"]["object"]
        return [
            self._make_event(
                "subscription.churned",
                customer_id=sub["customer"],
                external_id=sub["id"],
                occurred_at=self._occurred(sub),
                payload={
                    "external_id": sub["id"],
                    "prev_mrr_cents": self._compute_mrr(sub),
                },
            )
        ]

    # ── invoice handlers ─────────────────────────────────────────────────

    def _translate_invoice_created(self, wh: dict[str, Any]) -> list[Event]:
        inv = wh["data"]["object"]
        return [
            self._make_event(
                "invoice.created",
                customer_id=inv.get("customer", ""),
                external_id=inv["id"],
                occurred_at=self._occurred(inv),
                payload={
                    "external_id": inv["id"],
                    "customer_external_id": inv.get("customer"),
                    "subscription_external_id": inv.get("subscription"),
                    "status": inv.get("status"),
                    "currency": inv.get("currency"),
                    "subtotal_cents": inv.get("subtotal", 0),
                    "tax_cents": inv.get("tax", 0),
                    "total_cents": inv.get("total", 0),
                    "period_start": _ts(inv.get("period_start")),
                    "period_end": _ts(inv.get("period_end")),
                    "line_items": [
                        {
                            "description": li.get("description"),
                            "amount_cents": li.get("amount", 0),
                            "currency": li.get("currency"),
                            "quantity": li.get("quantity"),
                            "period_start": _ts((li.get("period") or {}).get("start")),
                            "period_end": _ts((li.get("period") or {}).get("end")),
                        }
                        for li in (inv.get("lines", {}).get("data", []))
                    ],
                },
            )
        ]

    def _translate_invoice_paid(self, wh: dict[str, Any]) -> list[Event]:
        inv = wh["data"]["object"]
        return [
            self._make_event(
                "invoice.paid",
                customer_id=inv.get("customer", ""),
                external_id=inv["id"],
                occurred_at=self._occurred(inv),
                payload={
                    "external_id": inv["id"],
                    "paid_at": _ts(inv.get("status_transitions", {}).get("paid_at")),
                    "amount_cents": inv.get("amount_paid", 0),
                },
            )
        ]

    def _translate_invoice_voided(self, wh: dict[str, Any]) -> list[Event]:
        inv = wh["data"]["object"]
        return [
            self._make_event(
                "invoice.voided",
                customer_id=inv.get("customer", ""),
                external_id=inv["id"],
                occurred_at=self._occurred(inv),
                payload={
                    "external_id": inv["id"],
                    "voided_at": _ts(inv.get("status_transitions", {}).get("voided_at")),
                },
            )
        ]

    def _translate_invoice_uncollectible(self, wh: dict[str, Any]) -> list[Event]:
        inv = wh["data"]["object"]
        return [
            self._make_event(
                "invoice.uncollectible",
                customer_id=inv.get("customer", ""),
                external_id=inv["id"],
                occurred_at=self._occurred(inv),
                payload={"external_id": inv["id"]},
            )
        ]

    # ── payment handlers ─────────────────────────────────────────────────

    def _translate_payment_succeeded(self, wh: dict[str, Any]) -> list[Event]:
        pi = wh["data"]["object"]
        return [
            self._make_event(
                "payment.succeeded",
                customer_id=pi.get("customer", ""),
                external_id=pi["id"],
                occurred_at=self._occurred(pi),
                payload={
                    "external_id": pi["id"],
                    "invoice_external_id": pi.get("invoice"),
                    "customer_external_id": pi.get("customer"),
                    "amount_cents": pi.get("amount", 0),
                    "currency": pi.get("currency"),
                    "payment_method_type": (pi.get("payment_method_types") or [None])[0],
                },
            )
        ]

    def _translate_payment_failed(self, wh: dict[str, Any]) -> list[Event]:
        pi = wh["data"]["object"]
        last_error = pi.get("last_payment_error") or {}
        return [
            self._make_event(
                "payment.failed",
                customer_id=pi.get("customer", ""),
                external_id=pi["id"],
                occurred_at=self._occurred(pi),
                payload={
                    "external_id": pi["id"],
                    "invoice_external_id": pi.get("invoice"),
                    "customer_external_id": pi.get("customer"),
                    "amount_cents": pi.get("amount", 0),
                    "failure_reason": last_error.get("message"),
                    "attempt_count": pi.get("metadata", {}).get("attempt_count"),
                },
            )
        ]

    def _translate_charge_refunded(self, wh: dict[str, Any]) -> list[Event]:
        charge = wh["data"]["object"]
        return [
            self._make_event(
                "payment.refunded",
                customer_id=charge.get("customer", ""),
                external_id=charge["id"],
                occurred_at=self._occurred(charge),
                payload={
                    "external_id": charge["id"],
                    "amount_cents": charge.get("amount_refunded", 0),
                    "refunded_at": _ts(charge.get("created")),
                },
            )
        ]

    # ── backfill ─────────────────────────────────────────────────────────

    async def backfill(self, since: datetime | None = None) -> AsyncIterator[Event]:
        """Pull historical data from Stripe API and yield internal events."""
        api_key: str = self.config["api_key"]
        stripe.api_key = api_key
        created_filter: dict[str, int] | None = {"gte": int(since.timestamp())} if since else None

        # Collect test clock IDs — test clock entities are invisible
        # to normal list calls and need an explicit test_clock filter.
        clock_ids: list[str | None] = [None]  # None = non-test-clock entities
        for clock in stripe.test_helpers.TestClock.list(limit=100).auto_paging_iter():
            clock_ids.append(clock.id)

        # 1. Customers
        for clock_id in clock_ids:
            params: dict[str, Any] = {"limit": 100}
            if created_filter:
                params["created"] = created_filter
            if clock_id:
                params["test_clock"] = clock_id
            for cust in stripe.Customer.list(**params).auto_paging_iter():
                yield self._make_event(
                    "customer.created",
                    customer_id=str(cust.id),
                    external_id=str(cust.id),
                    occurred_at=datetime.fromtimestamp(cust.created, tz=UTC),
                    payload={
                        "external_id": cust.id,
                        "name": cust.name,
                        "email": cust.email,
                        "currency": cust.currency,
                        "metadata": dict(cust.metadata or {}),
                    },
                )

        # 2. Subscriptions
        for clock_id in clock_ids:
            params = {"limit": 100, "status": "all"}
            if created_filter:
                params["created"] = created_filter
            if clock_id:
                params["test_clock"] = clock_id
            for sub in stripe.Subscription.list(**params).auto_paging_iter():
                sub_dict: dict[str, Any] = dict(sub)
                mrr = self._compute_mrr(sub_dict)
                occurred = datetime.fromtimestamp(sub.created, tz=UTC)
                plan_id = ""
                if sub.items and sub.items.data:
                    plan_id = str(sub.items.data[0].price.id)
                customer_id = str(sub.customer or "")

                yield self._make_event(
                    "subscription.created",
                    customer_id=customer_id,
                    external_id=str(sub.id),
                    occurred_at=occurred,
                    payload={
                        "external_id": sub.id,
                        "customer_external_id": sub.customer,
                        "plan_external_id": plan_id,
                        "status": sub.status,
                        "mrr_cents": mrr,
                        "quantity": sum(
                            (it.quantity or 1) for it in (sub.items.data if sub.items else [])
                        ),
                        "currency": sub.currency,
                        "started_at": _ts(sub.start_date),
                        "trial_start": _ts(sub.trial_start),
                        "trial_end": _ts(sub.trial_end),
                        "current_period_start": _ts(sub.current_period_start),  # type: ignore[attr-defined]
                        "current_period_end": _ts(sub.current_period_end),  # type: ignore[attr-defined]
                    },
                )
                if sub.status == "active":
                    yield self._make_event(
                        "subscription.activated",
                        customer_id=customer_id,
                        external_id=str(sub.id),
                        occurred_at=occurred,
                        payload={"external_id": sub.id, "mrr_cents": mrr},
                    )
                elif sub.status == "canceled":
                    yield self._make_event(
                        "subscription.churned",
                        customer_id=customer_id,
                        external_id=str(sub.id),
                        occurred_at=occurred,
                        payload={"external_id": sub.id, "prev_mrr_cents": mrr},
                    )

        # 3. Invoices (no test_clock filter needed — invoices are visible globally)
        params = {"limit": 100}
        if created_filter:
            params["created"] = created_filter
        for inv in stripe.Invoice.list(**params).auto_paging_iter():
            inv_customer = str(inv.customer or "")
            yield self._make_event(
                "invoice.created",
                customer_id=inv_customer,
                external_id=str(inv.id),
                occurred_at=datetime.fromtimestamp(inv.created, tz=UTC),
                payload={
                    "external_id": inv.id,
                    "customer_external_id": inv.customer,
                    "subscription_external_id": getattr(inv, "subscription", None),
                    "status": inv.status,
                    "currency": inv.currency,
                    "subtotal_cents": inv.subtotal or 0,
                    "tax_cents": getattr(inv, "tax", 0) or 0,
                    "total_cents": inv.total or 0,
                    "period_start": _ts(inv.period_start),
                    "period_end": _ts(inv.period_end),
                    "line_items": [],
                },
            )
            if inv.status == "paid":
                transitions = inv.status_transitions
                paid_at = transitions.paid_at if transitions else None
                yield self._make_event(
                    "invoice.paid",
                    customer_id=inv_customer,
                    external_id=str(inv.id),
                    occurred_at=datetime.fromtimestamp(inv.created, tz=UTC),
                    payload={
                        "external_id": inv.id,
                        "paid_at": _ts(paid_at),
                        "amount_cents": inv.amount_paid or 0,
                    },
                )

        # 4. Payment Intents
        params = {"limit": 100}
        if created_filter:
            params["created"] = created_filter
        for pi in stripe.PaymentIntent.list(**params).auto_paging_iter():
            if pi.status == "succeeded":
                yield self._make_event(
                    "payment.succeeded",
                    customer_id=str(pi.customer or ""),
                    external_id=str(pi.id),
                    occurred_at=datetime.fromtimestamp(pi.created, tz=UTC),
                    payload={
                        "external_id": pi.id,
                        "invoice_external_id": getattr(pi, "invoice", None),
                        "customer_external_id": pi.customer,
                        "amount_cents": pi.amount or 0,
                        "currency": pi.currency,
                        "payment_method_type": (
                            pi.payment_method_types[0] if pi.payment_method_types else None
                        ),
                    },
                )

    # ── helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _plan_id(sub: dict[str, Any]) -> str:
        """Extract the primary plan/price ID from a subscription dict."""
        items = sub.get("items", {})
        data = items.get("data", []) if isinstance(items, dict) else []
        if data:
            return str(data[0].get("price", {}).get("id", ""))
        plan = sub.get("plan")
        return str(plan.get("id", "")) if isinstance(plan, dict) else ""

    @staticmethod
    def _total_quantity(sub: dict[str, Any]) -> int:
        """Sum quantities across all subscription items."""
        items = sub.get("items", {})
        data = items.get("data", []) if isinstance(items, dict) else []
        return sum(item.get("quantity", 1) or 1 for item in data) if data else 1
