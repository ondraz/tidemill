"""Tests for the Stripe connector — translate() and _compute_mrr().

All tests are pure-Python, no database or network required.
"""

from __future__ import annotations

import pytest

from tidemill.connectors.stripe import StripeConnector

SRC = "src_test"


@pytest.fixture
def connector() -> StripeConnector:
    return StripeConnector(source_id=SRC, config={})


# ── _compute_mrr ─────────────────────────────────────────────────────────


def _sub(amount: int, interval: str = "month", interval_count: int = 1, qty: int = 1) -> dict:
    """Build a minimal Stripe subscription dict."""
    return {
        "items": {
            "data": [
                {
                    "price": {
                        "unit_amount": amount,
                        "recurring": {
                            "interval": interval,
                            "interval_count": interval_count,
                        },
                    },
                    "quantity": qty,
                }
            ]
        }
    }


class TestComputeMrr:
    def test_monthly(self, connector: StripeConnector):
        assert connector._compute_mrr(_sub(4999)) == 4999

    def test_yearly(self, connector: StripeConnector):
        assert connector._compute_mrr(_sub(59900, "year")) == 59900 // 12

    def test_weekly(self, connector: StripeConnector):
        assert connector._compute_mrr(_sub(1000, "week")) == int(1000 * 52 / 12)

    def test_daily(self, connector: StripeConnector):
        assert connector._compute_mrr(_sub(100, "day")) == int(100 * 365 / 12)

    def test_quarterly(self, connector: StripeConnector):
        """interval=month, interval_count=3 → quarterly."""
        assert connector._compute_mrr(_sub(9000, "month", 3)) == 3000

    def test_biannual(self, connector: StripeConnector):
        """interval=year, interval_count=2."""
        assert connector._compute_mrr(_sub(120000, "year", 2)) == 120000 // 24

    def test_quantity(self, connector: StripeConnector):
        assert connector._compute_mrr(_sub(1000, qty=5)) == 5000

    def test_multi_item(self, connector: StripeConnector):
        sub = {
            "items": {
                "data": [
                    {
                        "price": {
                            "unit_amount": 2000,
                            "recurring": {"interval": "month", "interval_count": 1},
                        },
                        "quantity": 1,
                    },
                    {
                        "price": {
                            "unit_amount": 500,
                            "recurring": {"interval": "month", "interval_count": 1},
                        },
                        "quantity": 3,
                    },
                ]
            }
        }
        assert connector._compute_mrr(sub) == 2000 + 1500

    def test_metered_excluded(self, connector: StripeConnector):
        """Metered (usage-based) prices should not count toward MRR."""
        sub = {
            "items": {
                "data": [
                    {
                        "price": {
                            "unit_amount": 2000,
                            "recurring": {"interval": "month", "interval_count": 1},
                        },
                        "quantity": 1,
                    },
                    {
                        "price": {
                            "unit_amount": 100,
                            "recurring": {
                                "interval": "month",
                                "interval_count": 1,
                                "usage_type": "metered",
                            },
                        },
                        "quantity": 1,
                    },
                ]
            }
        }
        assert connector._compute_mrr(sub) == 2000

    def test_empty_items(self, connector: StripeConnector):
        assert connector._compute_mrr({"items": {"data": []}}) == 0

    def test_missing_items(self, connector: StripeConnector):
        assert connector._compute_mrr({}) == 0


# ── Webhook helpers ──────────────────────────────────────────────────────


def _customer_wh(event_type: str, cust_id: str = "cus_1", **extra) -> dict:
    obj = {
        "id": cust_id,
        "created": 1700000000,
        "name": "Test",
        "email": "t@e.co",
        "currency": "usd",
        "metadata": {},
        **extra,
    }
    return {"type": event_type, "data": {"object": obj}}


def _sub_wh(
    event_type: str,
    sub_id: str = "sub_1",
    cust_id: str = "cus_1",
    status: str = "active",
    amount: int = 5000,
    prev_attrs: dict | None = None,
) -> dict:
    obj = {
        "id": sub_id,
        "customer": cust_id,
        "status": status,
        "created": 1700000000,
        "currency": "usd",
        "start_date": 1700000000,
        "trial_start": None,
        "trial_end": None,
        "current_period_start": 1700000000,
        "current_period_end": 1702592000,
        "canceled_at": None,
        "cancel_at_period_end": False,
        "pause_collection": None,
        "items": {
            "data": [
                {
                    "price": {
                        "id": "price_1",
                        "unit_amount": amount,
                        "recurring": {"interval": "month", "interval_count": 1},
                    },
                    "quantity": 1,
                }
            ]
        },
    }
    wh: dict = {"type": event_type, "data": {"object": obj}}
    if prev_attrs is not None:
        wh["data"]["previous_attributes"] = prev_attrs
    return wh


# ── Product / Price translations ─────────────────────────────────────────


def _product_wh(event_type: str, prod_id: str = "prod_1", **extra) -> dict:
    obj = {
        "id": prod_id,
        "object": "product",
        "name": "Pro",
        "description": "Pro tier",
        "active": True,
        "created": 1700000000,
        "metadata": {"tier": "pro"},
        **extra,
    }
    return {"type": event_type, "data": {"object": obj}, "created": 1700000000}


def _price_wh(
    event_type: str,
    price_id: str = "price_1",
    product_id: str = "prod_1",
    **extra,
) -> dict:
    obj = {
        "id": price_id,
        "object": "price",
        "active": True,
        "created": 1700000000,
        "currency": "usd",
        "unit_amount": 9900,
        "billing_scheme": "per_unit",
        "nickname": "Pro Monthly",
        "product": product_id,
        "recurring": {
            "interval": "month",
            "interval_count": 1,
            "usage_type": "licensed",
            "trial_period_days": 14,
        },
        "metadata": {},
        **extra,
    }
    return {"type": event_type, "data": {"object": obj}, "created": 1700000000}


class TestProductTranslation:
    def test_created(self, connector: StripeConnector):
        events = connector.translate(_product_wh("product.created"))
        assert len(events) == 1
        assert events[0].type == "product.created"
        assert events[0].customer_id == ""
        assert events[0].payload["external_id"] == "prod_1"
        assert events[0].payload["name"] == "Pro"
        assert events[0].payload["active"] is True
        assert events[0].payload["metadata"] == {"tier": "pro"}

    def test_updated(self, connector: StripeConnector):
        events = connector.translate(_product_wh("product.updated", active=False))
        assert len(events) == 1
        assert events[0].type == "product.updated"
        assert events[0].payload["active"] is False

    def test_updated_uses_webhook_event_time(self, connector: StripeConnector):
        """Use webhook event time for product.updated, not the product's original ``created``."""
        wh = _product_wh("product.updated", created=1700000000)
        wh["created"] = 1700100000  # webhook event time, later than product.created
        events = connector.translate(wh)
        assert events[0].occurred_at.timestamp() == 1700100000

    def test_deleted(self, connector: StripeConnector):
        events = connector.translate(_product_wh("product.deleted"))
        assert len(events) == 1
        assert events[0].type == "product.deleted"
        assert events[0].payload == {"external_id": "prod_1"}


class TestPriceTranslation:
    def test_created(self, connector: StripeConnector):
        events = connector.translate(_price_wh("price.created"))
        assert len(events) == 1
        assert events[0].type == "plan.created"
        assert events[0].customer_id == ""
        p = events[0].payload
        assert p["external_id"] == "price_1"
        assert p["product_external_id"] == "prod_1"
        assert p["interval"] == "month"
        assert p["interval_count"] == 1
        assert p["amount_cents"] == 9900
        assert p["currency"] == "usd"
        assert p["billing_scheme"] == "per_unit"
        assert p["usage_type"] == "licensed"
        assert p["trial_period_days"] == 14
        assert p["name"] == "Pro Monthly"

    def test_created_metered_no_unit_amount(self, connector: StripeConnector):
        wh = _price_wh(
            "price.created",
            unit_amount=None,
            billing_scheme="tiered",
            recurring={"interval": "month", "interval_count": 1, "usage_type": "metered"},
        )
        events = connector.translate(wh)
        assert events[0].payload["amount_cents"] is None
        assert events[0].payload["billing_scheme"] == "tiered"
        assert events[0].payload["usage_type"] == "metered"
        assert events[0].payload["trial_period_days"] is None

    def test_updated(self, connector: StripeConnector):
        events = connector.translate(_price_wh("price.updated", active=False))
        assert events[0].type == "plan.updated"
        assert events[0].payload["active"] is False

    def test_updated_uses_webhook_event_time(self, connector: StripeConnector):
        """Use webhook event time for price.updated, not the price's original ``created``."""
        wh = _price_wh("price.updated", created=1700000000)
        wh["created"] = 1700100000  # webhook event time, later than price.created
        events = connector.translate(wh)
        assert events[0].occurred_at.timestamp() == 1700100000

    def test_deleted(self, connector: StripeConnector):
        events = connector.translate(_price_wh("price.deleted"))
        assert events[0].type == "plan.deleted"
        assert events[0].payload == {"external_id": "price_1"}

    def test_non_recurring_price_emits_no_event(self, connector: StripeConnector):
        """One-time Stripe Prices (no ``recurring`` block) emit no plan.* events."""
        wh_created = _price_wh("price.created", recurring=None)
        wh_updated = _price_wh("price.updated", recurring=None)
        wh_deleted = _price_wh("price.deleted", recurring=None)
        assert connector.translate(wh_created) == []
        assert connector.translate(wh_updated) == []
        assert connector.translate(wh_deleted) == []


# ── Customer translations ────────────────────────────────────────────────


class TestCustomerTranslation:
    def test_created(self, connector: StripeConnector):
        events = connector.translate(_customer_wh("customer.created"))
        assert len(events) == 1
        assert events[0].type == "customer.created"
        assert events[0].customer_id == "cus_1"
        assert events[0].payload["external_id"] == "cus_1"
        assert events[0].payload["name"] == "Test"

    def test_updated(self, connector: StripeConnector):
        wh = _customer_wh("customer.updated")
        wh["data"]["previous_attributes"] = {"name": "Old Name"}
        events = connector.translate(wh)
        assert len(events) == 1
        assert events[0].type == "customer.updated"
        assert events[0].payload["changed_fields"] == {"name": "Old Name"}

    def test_deleted(self, connector: StripeConnector):
        events = connector.translate(_customer_wh("customer.deleted"))
        assert len(events) == 1
        assert events[0].type == "customer.deleted"


# ── Subscription translations ────────────────────────────────────────────


class TestSubscriptionTranslation:
    def test_created_active(self, connector: StripeConnector):
        events = connector.translate(_sub_wh("customer.subscription.created", status="active"))
        assert len(events) == 2
        assert events[0].type == "subscription.created"
        assert events[0].payload["mrr_cents"] == 5000
        assert events[0].payload["status"] == "active"
        assert events[1].type == "subscription.activated"
        assert events[1].payload["mrr_cents"] == 5000

    def test_created_trialing_emits_trial_started(self, connector: StripeConnector):
        wh = _sub_wh("customer.subscription.created", status="trialing")
        wh["data"]["object"]["trial_start"] = 1700000000
        wh["data"]["object"]["trial_end"] = 1701000000
        events = connector.translate(wh)
        assert len(events) == 2
        assert events[0].type == "subscription.created"
        assert events[1].type == "subscription.trial_started"

    def test_updated_trial_to_active(self, connector: StripeConnector):
        events = connector.translate(
            _sub_wh(
                "customer.subscription.updated",
                status="active",
                prev_attrs={"status": "trialing"},
            )
        )
        types = [e.type for e in events]
        assert "subscription.trial_converted" in types
        assert "subscription.activated" in types

    def test_updated_trial_expired(self, connector: StripeConnector):
        events = connector.translate(
            _sub_wh(
                "customer.subscription.updated",
                status="canceled",
                prev_attrs={"status": "trialing"},
            )
        )
        assert any(e.type == "subscription.trial_expired" for e in events)

    def test_updated_trial_incomplete_expired(self, connector: StripeConnector):
        events = connector.translate(
            _sub_wh(
                "customer.subscription.updated",
                status="incomplete_expired",
                prev_attrs={"status": "trialing"},
            )
        )
        assert any(e.type == "subscription.trial_expired" for e in events)

    def test_updated_to_active(self, connector: StripeConnector):
        events = connector.translate(
            _sub_wh(
                "customer.subscription.updated",
                status="active",
                prev_attrs={"status": "past_due"},
            )
        )
        assert any(e.type == "subscription.activated" for e in events)

    def test_updated_canceled(self, connector: StripeConnector):
        events = connector.translate(
            _sub_wh(
                "customer.subscription.updated",
                status="canceled",
                prev_attrs={"status": "active"},
            )
        )
        assert any(e.type == "subscription.canceled" for e in events)

    def test_updated_paused(self, connector: StripeConnector):
        events = connector.translate(
            _sub_wh(
                "customer.subscription.updated",
                status="paused",
                prev_attrs={"status": "active"},
            )
        )
        assert any(e.type == "subscription.paused" for e in events)

    def test_updated_plan_change(self, connector: StripeConnector):
        """Changing items triggers subscription.changed with prev/new MRR."""
        prev_items = {
            "data": [
                {
                    "price": {
                        "id": "price_old",
                        "unit_amount": 3000,
                        "recurring": {"interval": "month", "interval_count": 1},
                    },
                    "quantity": 1,
                }
            ]
        }
        events = connector.translate(
            _sub_wh(
                "customer.subscription.updated",
                amount=5000,
                prev_attrs={"items": prev_items},
            )
        )
        changed = [e for e in events if e.type == "subscription.changed"]
        assert len(changed) == 1
        assert changed[0].payload["prev_mrr_cents"] == 3000
        assert changed[0].payload["new_mrr_cents"] == 5000

    def test_updated_no_mrr_change_no_event(self, connector: StripeConnector):
        """Same MRR → no subscription.changed event."""
        same_items = {
            "data": [
                {
                    "price": {
                        "id": "price_1",
                        "unit_amount": 5000,
                        "recurring": {"interval": "month", "interval_count": 1},
                    },
                    "quantity": 1,
                }
            ]
        }
        events = connector.translate(
            _sub_wh(
                "customer.subscription.updated",
                amount=5000,
                prev_attrs={"items": same_items},
            )
        )
        assert not any(e.type == "subscription.changed" for e in events)

    def test_updated_resumed_from_pause(self, connector: StripeConnector):
        wh = _sub_wh(
            "customer.subscription.updated",
            status="active",
            prev_attrs={"pause_collection": {"behavior": "mark_uncollectible"}},
        )
        events = connector.translate(wh)
        assert any(e.type == "subscription.resumed" for e in events)

    def test_updated_cancel_at_period_end(self, connector: StripeConnector):
        wh = _sub_wh(
            "customer.subscription.updated",
            status="active",
            prev_attrs={"cancel_at_period_end": False},
        )
        wh["data"]["object"]["cancel_at_period_end"] = True
        events = connector.translate(wh)
        assert any(e.type == "subscription.canceled" for e in events)

    def test_deleted(self, connector: StripeConnector):
        events = connector.translate(_sub_wh("customer.subscription.deleted", amount=5000))
        assert len(events) == 1
        assert events[0].type == "subscription.churned"
        assert events[0].payload["prev_mrr_cents"] == 5000

    def test_deleted_mid_trial_emits_trial_expired(self, connector: StripeConnector):
        """Mid-trial deletion still emits a trial_expired event.

        Stripe can fire `customer.subscription.deleted` directly on a
        mid-trial cancellation (no preceding ``trialing → canceled`` update).
        The handler must still close out the trial cohort.
        """
        wh = _sub_wh("customer.subscription.deleted", status="canceled")
        wh["data"]["object"]["trial_start"] = 1700000000
        wh["data"]["object"]["trial_end"] = 1702000000
        wh["data"]["object"]["ended_at"] = 1701000000  # before trial_end
        events = connector.translate(wh)
        types = {e.type for e in events}
        assert types == {"subscription.churned", "subscription.trial_expired"}

    def test_deleted_after_trial_no_trial_expired(self, connector: StripeConnector):
        """Post-trial deletion does not emit trial_expired.

        Deletion after trial converted (ended_at >= trial_end) is just a
        churn — not a trial expiry.
        """
        wh = _sub_wh("customer.subscription.deleted", status="canceled")
        wh["data"]["object"]["trial_start"] = 1700000000
        wh["data"]["object"]["trial_end"] = 1702000000
        wh["data"]["object"]["ended_at"] = 1703000000  # after trial_end
        events = connector.translate(wh)
        assert [e.type for e in events] == ["subscription.churned"]

    def test_deleted_while_trialing_emits_trial_expired(self, connector: StripeConnector):
        """Deletion while still trialing emits trial_expired.

        If the deleted webhook still reports ``status=trialing`` (no
        ``ended_at`` reached us), trust the status as the signal.
        """
        wh = _sub_wh("customer.subscription.deleted", status="trialing")
        wh["data"]["object"]["trial_start"] = 1700000000
        wh["data"]["object"]["trial_end"] = 1702000000
        events = connector.translate(wh)
        types = {e.type for e in events}
        assert types == {"subscription.churned", "subscription.trial_expired"}


# ── Timestamp attribution (_sub_occurred) ──────────────────────────────────


class TestSubOccurred:
    """Verify that _sub_occurred picks the correct simulated timestamp."""

    def test_plan_change_uses_item_created(self):
        """Plan change: use the newest item ``created`` (simulated time)."""
        sub = {
            "status": "active",
            "created": 1693526400,  # 2023-09-01 (sim)
            "canceled_at": None,
            "ended_at": None,
            "trial_end": None,
            "items": {
                "data": [
                    {"created": 1696118400, "price": {"id": "p1"}},  # 2023-10-01 (sim)
                    {"created": 1696118400, "price": {"id": "p2"}},
                ]
            },
        }
        wh = {"created": 1743800000}  # wall-clock (far future)
        result = StripeConnector._sub_occurred(sub, wh)
        assert result.year == 2023
        assert result.month == 10

    def test_trial_conversion_uses_trial_end(self):
        """Trial → active: ``trial_end`` is newer than item ``created``."""
        sub = {
            "status": "active",
            "created": 1693526400,  # 2023-09-01 (sim)
            "canceled_at": None,
            "ended_at": None,
            "trial_end": 1696118400,  # 2023-10-01 (sim)
            "items": {
                "data": [
                    {"created": 1693526400, "price": {"id": "p1"}},  # original items
                ]
            },
        }
        wh = {"created": 1743800000}
        result = StripeConnector._sub_occurred(sub, wh)
        assert result.year == 2023
        assert result.month == 10

    def test_canceled_at_takes_priority(self):
        """Cancellation: ``canceled_at`` beats everything else."""
        sub = {
            "status": "canceled",
            "created": 1693526400,
            "canceled_at": 1701388800,  # 2023-12-01
            "ended_at": None,
            "trial_end": 1696118400,
            "items": {"data": [{"created": 1693526400, "price": {"id": "p1"}}]},
        }
        wh = {"created": 1743800000}
        result = StripeConnector._sub_occurred(sub, wh)
        assert result.year == 2023
        assert result.month == 12

    def test_production_sub_uses_wh_created(self):
        """Non-test-clock sub with no item timestamps: fall back to wh created."""
        sub = {
            "status": "active",
            "created": 1693526400,
            "canceled_at": None,
            "ended_at": None,
            "trial_end": None,
            "items": {"data": []},
        }
        wh = {"created": 1696118400}  # 2023-10-01
        result = StripeConnector._sub_occurred(sub, wh)
        assert result.year == 2023
        assert result.month == 10


# ── Invoice translations ─────────────────────────────────────────────────


def _invoice_wh(event_type: str, inv_id: str = "in_1") -> dict:
    obj = {
        "id": inv_id,
        "customer": "cus_1",
        "subscription": "sub_1",
        "status": "open",
        "currency": "usd",
        "subtotal": 5000,
        "tax": 0,
        "total": 5000,
        "amount_paid": 5000,
        "period_start": 1700000000,
        "period_end": 1702592000,
        "created": 1700000000,
        "lines": {"data": []},
        "status_transitions": {"paid_at": 1700100000, "voided_at": 1700100000},
    }
    return {"type": event_type, "data": {"object": obj}}


class TestInvoiceTranslation:
    def test_created(self, connector: StripeConnector):
        events = connector.translate(_invoice_wh("invoice.created"))
        assert len(events) == 1
        assert events[0].type == "invoice.created"
        assert events[0].payload["total_cents"] == 5000

    def test_paid(self, connector: StripeConnector):
        events = connector.translate(_invoice_wh("invoice.paid"))
        assert len(events) == 1
        assert events[0].type == "invoice.paid"
        assert events[0].payload["amount_cents"] == 5000

    def test_voided(self, connector: StripeConnector):
        events = connector.translate(_invoice_wh("invoice.voided"))
        assert len(events) == 1
        assert events[0].type == "invoice.voided"

    def test_uncollectible(self, connector: StripeConnector):
        events = connector.translate(_invoice_wh("invoice.marked_uncollectible"))
        assert len(events) == 1
        assert events[0].type == "invoice.uncollectible"


# ── Payment translations ─────────────────────────────────────────────────


class TestPaymentTranslation:
    def test_succeeded(self, connector: StripeConnector):
        wh = {
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_1",
                    "customer": "cus_1",
                    "invoice": "in_1",
                    "amount": 5000,
                    "currency": "usd",
                    "created": 1700000000,
                    "payment_method_types": ["card"],
                }
            },
        }
        events = connector.translate(wh)
        assert len(events) == 1
        assert events[0].type == "payment.succeeded"
        assert events[0].payload["amount_cents"] == 5000
        assert events[0].payload["payment_method_type"] == "card"

    def test_failed(self, connector: StripeConnector):
        wh = {
            "type": "payment_intent.payment_failed",
            "data": {
                "object": {
                    "id": "pi_1",
                    "customer": "cus_1",
                    "invoice": "in_1",
                    "amount": 5000,
                    "currency": "usd",
                    "created": 1700000000,
                    "payment_method_types": ["card"],
                    "last_payment_error": {"message": "Card declined"},
                    "metadata": {},
                }
            },
        }
        events = connector.translate(wh)
        assert len(events) == 1
        assert events[0].type == "payment.failed"
        assert events[0].payload["failure_reason"] == "Card declined"

    def test_refunded(self, connector: StripeConnector):
        wh = {
            "type": "charge.refunded",
            "data": {
                "object": {
                    "id": "ch_1",
                    "customer": "cus_1",
                    "amount_refunded": 2500,
                    "created": 1700000000,
                }
            },
        }
        events = connector.translate(wh)
        assert len(events) == 1
        assert events[0].type == "payment.refunded"
        assert events[0].payload["amount_cents"] == 2500


# ── Misc ─────────────────────────────────────────────────────────────────


class TestMisc:
    def test_unknown_type_returns_empty(self, connector: StripeConnector):
        assert connector.translate({"type": "unknown.event", "data": {"object": {}}}) == []

    def test_verify_signature_no_secret(self, connector: StripeConnector):
        """Without a webhook_secret, verification always passes."""
        assert connector.verify_signature(b"payload", "sig_xxx") is True

    def test_event_ids_are_deterministic(self, connector: StripeConnector):
        wh = _customer_wh("customer.created")
        e1 = connector.translate(wh)
        e2 = connector.translate(wh)
        assert e1[0].id == e2[0].id

    def test_event_source_id_matches_connector(self, connector: StripeConnector):
        events = connector.translate(_customer_wh("customer.created"))
        assert events[0].source_id == SRC


class TestBackfillTrialEvents:
    """Trial lifecycle reconstruction from a subscription snapshot."""

    @staticmethod
    def _sub(
        status: str, trial_start: int | None, trial_end: int | None, ended_at: int | None = None
    ) -> dict:
        return {
            "id": "sub_test",
            "status": status,
            "trial_start": trial_start,
            "trial_end": trial_end,
            "ended_at": ended_at,
        }

    def test_no_trial_emits_nothing(self, connector: StripeConnector):
        sub = self._sub("active", trial_start=None, trial_end=None)
        assert list(connector._backfill_trial_events(sub, "cus_1", mrr=1000)) == []

    def test_still_trialing_emits_started_only(self, connector: StripeConnector):
        sub = self._sub("trialing", trial_start=1700000000, trial_end=1701000000)
        events = list(connector._backfill_trial_events(sub, "cus_1", mrr=1000))
        assert [e.type for e in events] == ["subscription.trial_started"]

    def test_active_emits_started_and_converted(self, connector: StripeConnector):
        sub = self._sub("active", trial_start=1700000000, trial_end=1701000000)
        events = list(connector._backfill_trial_events(sub, "cus_1", mrr=1000))
        assert [e.type for e in events] == [
            "subscription.trial_started",
            "subscription.trial_converted",
        ]

    def test_incomplete_expired_emits_started_and_expired(self, connector: StripeConnector):
        sub = self._sub("incomplete_expired", trial_start=1700000000, trial_end=1701000000)
        events = list(connector._backfill_trial_events(sub, "cus_1", mrr=1000))
        assert [e.type for e in events] == [
            "subscription.trial_started",
            "subscription.trial_expired",
        ]

    def test_canceled_during_trial_emits_expired(self, connector: StripeConnector):
        # ended_at < trial_end → canceled before conversion
        sub = self._sub(
            "canceled",
            trial_start=1700000000,
            trial_end=1701000000,
            ended_at=1700500000,
        )
        events = list(connector._backfill_trial_events(sub, "cus_1", mrr=1000))
        assert [e.type for e in events] == [
            "subscription.trial_started",
            "subscription.trial_expired",
        ]

    def test_canceled_at_trial_end_emits_converted(self, connector: StripeConnector):
        # ended_at == trial_end → ambiguous; favour converted (sub did
        # transition through active even if canceled immediately after)
        sub = self._sub(
            "canceled",
            trial_start=1700000000,
            trial_end=1701000000,
            ended_at=1701000000,
        )
        events = list(connector._backfill_trial_events(sub, "cus_1", mrr=1000))
        assert [e.type for e in events] == [
            "subscription.trial_started",
            "subscription.trial_converted",
        ]

    def test_canceled_after_conversion_emits_converted(self, connector: StripeConnector):
        # ended_at > trial_end → converted, then churned later
        sub = self._sub(
            "canceled",
            trial_start=1700000000,
            trial_end=1701000000,
            ended_at=1702000000,
        )
        events = list(connector._backfill_trial_events(sub, "cus_1", mrr=1000))
        assert [e.type for e in events] == [
            "subscription.trial_started",
            "subscription.trial_converted",
        ]
