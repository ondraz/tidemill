"""Tests for the Chargebee connector — translate() and verify_signature().

Pure-Python; no network or database needed. The fixtures use minimal
Chargebee webhook shapes (the ``content`` wrapper + the relevant entity
sub-object) so each test exercises one mapping at a time.
"""

from __future__ import annotations

import base64

import pytest

from tidemill.connectors.chargebee import ChargebeeConnector

SRC = "src_cb_test"


@pytest.fixture
def connector() -> ChargebeeConnector:
    return ChargebeeConnector(source_id=SRC, config={})


# ── Webhook helpers ──────────────────────────────────────────────────────


def _wh(event_type: str, content: dict, occurred_at: int = 1_700_000_000) -> dict:
    return {
        "id": f"ev_{event_type}",
        "event_type": event_type,
        "occurred_at": occurred_at,
        "content": content,
    }


# ── Customer translation ────────────────────────────────────────────────


class TestCustomer:
    def test_created(self, connector: ChargebeeConnector):
        wh = _wh(
            "customer_created",
            {
                "customer": {
                    "id": "cb_cust_1",
                    "first_name": "Acme Co",
                    "email": "a@e.co",
                    "preferred_currency_code": "USD",
                    "billing_address": {"country": "US"},
                    "meta_data": {"tier": "starter"},
                }
            },
        )
        events = connector.translate(wh)
        assert len(events) == 1
        assert events[0].type == "customer.created"
        assert events[0].customer_id == "cb_cust_1"
        assert events[0].payload["external_id"] == "cb_cust_1"
        assert events[0].payload["email"] == "a@e.co"
        assert events[0].payload["country"] == "US"
        assert events[0].payload["currency"] == "usd"

    def test_deleted(self, connector: ChargebeeConnector):
        events = connector.translate(_wh("customer_deleted", {"customer": {"id": "cb_cust_1"}}))
        assert events[0].type == "customer.deleted"
        assert events[0].payload == {"external_id": "cb_cust_1"}


# ── Catalog (Item / Item Price) translation ──────────────────────────────


class TestCatalog:
    def test_item_created(self, connector: ChargebeeConnector):
        events = connector.translate(
            _wh(
                "item_created",
                {"item": {"id": "starter", "name": "Starter", "status": "active"}},
            )
        )
        assert events[0].type == "product.created"
        assert events[0].payload["external_id"] == "starter"
        assert events[0].payload["active"] is True

    def test_item_price_created_recurring(self, connector: ChargebeeConnector):
        events = connector.translate(
            _wh(
                "item_price_created",
                {
                    "item_price": {
                        "id": "starter-USD-monthly",
                        "item_id": "starter",
                        "price": 2000,
                        "currency_code": "USD",
                        "period": 1,
                        "period_unit": "month",
                        "pricing_model": "flat_fee",
                        "status": "active",
                    }
                },
            )
        )
        assert events[0].type == "plan.created"
        p = events[0].payload
        assert p["interval"] == "month"
        assert p["interval_count"] == 1
        assert p["amount_cents"] == 2000
        assert p["currency"] == "usd"
        assert p["pricing_model"] == "flat"
        assert p["usage_type"] == "licensed"
        assert p["product_external_id"] == "starter"

    def test_item_price_created_non_recurring_is_skipped(self, connector: ChargebeeConnector):
        """One-off charge_item_prices have no period — we don't ingest them."""
        events = connector.translate(
            _wh(
                "item_price_created",
                {
                    "item_price": {
                        "id": "one-off",
                        "item_id": "fee",
                        "price": 500,
                        "currency_code": "USD",
                        # period/period_unit deliberately omitted
                        "pricing_model": "flat_fee",
                    }
                },
            )
        )
        assert events == []


# ── Subscription translation ─────────────────────────────────────────────


def _sub(
    *,
    status: str = "active",
    mrr: int = 7900,
    sub_id: str = "cb_sub_1",
    cust_id: str = "cb_cust_1",
    items: list[dict] | None = None,
) -> dict:
    return {
        "id": sub_id,
        "customer_id": cust_id,
        "status": status,
        "currency_code": "USD",
        "mrr": mrr,
        "started_at": 1_700_000_000,
        "current_term_start": 1_700_000_000,
        "current_term_end": 1_702_592_000,
        "subscription_items": items
        or [
            {
                "item_price_id": "professional-USD-monthly",
                "item_type": "plan",
                "amount": mrr,
                "quantity": 1,
            }
        ],
    }


class TestSubscription:
    def test_created_active(self, connector: ChargebeeConnector):
        events = connector.translate(_wh("subscription_created", {"subscription": _sub()}))
        types = [e.type for e in events]
        # Active subs get the canonical created + activated pair so the
        # MRR snapshot writer fires its onboarding path identically to
        # how the Stripe connector emits things.
        assert types == ["subscription.created", "subscription.activated"]
        created = events[0]
        assert created.payload["status"] == "active"
        assert created.payload["mrr_cents"] == 7900  # server-side, no recompute
        assert created.payload["plan_external_id"] == "professional-USD-monthly"
        assert created.payload["pending_cancellation"] is False
        assert len(created.payload["items"]) == 1

    def test_created_in_trial_emits_trial_started(self, connector: ChargebeeConnector):
        sub = _sub(status="in_trial", mrr=0)
        sub["trial_start"] = 1_700_000_000
        sub["trial_end"] = 1_702_500_000
        events = connector.translate(_wh("subscription_created", {"subscription": sub}))
        types = [e.type for e in events]
        assert types == ["subscription.created", "subscription.trial_started"]
        assert events[0].payload["status"] == "trialing"

    def test_non_renewing_sets_pending_cancellation(self, connector: ChargebeeConnector):
        """Chargebee's ``non_renewing`` collapses to canonical active + flag.

        The subscription is still active for billing this period, but
        ``pending_cancellation`` flips on so dashboards can flag the
        upcoming churn.
        """
        sub = _sub(status="non_renewing")
        events = connector.translate(_wh("subscription_changed", {"subscription": sub}))
        # No prior_subscription on this fixture so the canonical event
        # uses status from current sub; payload still carries the flag.
        # We assert by walking the subscription_payload through the
        # ``subscription_changed`` handler.
        sub_with_prior = {
            "subscription": _sub(status="non_renewing"),
            "prior_subscription": _sub(status="active"),
        }
        sub_with_prior["subscription"]["mrr"] = 7900
        sub_with_prior["prior_subscription"]["mrr"] = 7900
        events = connector.translate(_wh("subscription_changed", sub_with_prior))
        # MRR unchanged so we expect zero events from the change path,
        # but the *created* path is the one that materialises the
        # canonical payload — assert it there instead.
        events = connector.translate(
            _wh("subscription_created", {"subscription": _sub(status="non_renewing")})
        )
        assert events[0].payload["status"] == "active"
        assert events[0].payload["pending_cancellation"] is True

    def test_cancelled(self, connector: ChargebeeConnector):
        sub = _sub(status="cancelled")
        sub["cancelled_at"] = 1_702_500_000
        sub["cancel_reason"] = "not_paid"
        events = connector.translate(_wh("subscription_cancelled", {"subscription": sub}))
        assert events[0].type == "subscription.canceled"
        assert events[0].payload["cancel_reason"] == "not_paid"

    def test_deleted_is_churn(self, connector: ChargebeeConnector):
        events = connector.translate(_wh("subscription_deleted", {"subscription": _sub()}))
        assert events[0].type == "subscription.churned"
        assert events[0].payload["prev_mrr_cents"] == 7900

    def test_changed_no_mrr_delta_emits_nothing(self, connector: ChargebeeConnector):
        wh = _wh(
            "subscription_changed",
            {
                "subscription": _sub(mrr=7900),
                "prior_subscription": _sub(mrr=7900),
            },
        )
        events = connector.translate(wh)
        assert events == []

    def test_changed_with_mrr_delta_emits_event(self, connector: ChargebeeConnector):
        wh = _wh(
            "subscription_changed",
            {
                "subscription": _sub(mrr=9900),
                "prior_subscription": _sub(mrr=7900),
            },
        )
        events = connector.translate(wh)
        assert events[0].type == "subscription.changed"
        p = events[0].payload
        assert p["prev_mrr_cents"] == 7900
        assert p["new_mrr_cents"] == 9900
        assert p["items"][0]["external_id"] == "professional-USD-monthly"


# ── Invoice / payment / credit_note / coupon translation ────────────────


class TestInvoice:
    def test_invoice_generated_paid(self, connector: ChargebeeConnector):
        events = connector.translate(
            _wh(
                "invoice_generated",
                {
                    "invoice": {
                        "id": "inv_1",
                        "customer_id": "cb_cust_1",
                        "subscription_id": "cb_sub_1",
                        "status": "paid",
                        "currency_code": "USD",
                        "sub_total": 7900,
                        "tax": 0,
                        "total": 7900,
                        "amount_paid": 7900,
                        "paid_at": 1_700_000_000,
                        "line_items": [],
                    }
                },
            )
        )
        types = [e.type for e in events]
        assert types == ["invoice.created", "invoice.paid"]
        assert events[0].payload["status"] == "paid"


class TestPayment:
    def test_succeeded(self, connector: ChargebeeConnector):
        events = connector.translate(
            _wh(
                "payment_succeeded",
                {
                    "transaction": {
                        "id": "txn_1",
                        "customer_id": "cb_cust_1",
                        "amount": 7900,
                        "currency_code": "USD",
                        "payment_method": "card",
                        "linked_invoices": [{"invoice_id": "inv_1"}],
                    }
                },
            )
        )
        assert events[0].type == "payment.succeeded"
        assert events[0].payload["amount_cents"] == 7900
        assert events[0].payload["payment_method_type"] == "card"
        assert events[0].payload["invoice_external_id"] == "inv_1"


class TestCoupon:
    def test_created_repeating(self, connector: ChargebeeConnector):
        events = connector.translate(
            _wh(
                "coupon_created",
                {
                    "coupon": {
                        "id": "WELCOME10",
                        "name": "Welcome 10%",
                        "discount_percentage": 10,
                        "duration_type": "limited_period",
                        "period_unit": "month",
                        "period": 3,
                        "status": "active",
                    }
                },
            )
        )
        assert events[0].type == "coupon.created"
        p = events[0].payload
        assert p["duration"] == "repeating"
        assert p["duration_in_months"] == 3
        assert p["percent_off"] == 10

    def test_one_time_maps_to_once(self, connector: ChargebeeConnector):
        events = connector.translate(
            _wh(
                "coupon_created",
                {
                    "coupon": {
                        "id": "SHIRT",
                        "discount_amount": 500,
                        "duration_type": "one_time",
                        "status": "active",
                        "currency_code": "USD",
                    }
                },
            )
        )
        assert events[0].payload["duration"] == "once"
        assert events[0].payload["amount_off_cents"] == 500


class TestCreditNote:
    def test_created_with_canonical_reason(self, connector: ChargebeeConnector):
        events = connector.translate(
            _wh(
                "credit_note_created",
                {
                    "credit_note": {
                        "id": "cn_1",
                        "customer_id": "cb_cust_1",
                        "reference_invoice_id": "inv_1",
                        "status": "refunded",
                        "reason_code": "cancellation",  # → order_change
                        "currency_code": "USD",
                        "sub_total": 1000,
                        "total_tax": 0,
                        "total": 1000,
                    }
                },
            )
        )
        assert events[0].type == "credit_note.created"
        p = events[0].payload
        assert p["status"] == "issued"
        assert p["reason"] == "order_change"  # canonical mapping from cancellation
        assert p["total_cents"] == 1000

    def test_voided_via_update_emits_voided(self, connector: ChargebeeConnector):
        events = connector.translate(
            _wh(
                "credit_note_updated",
                {
                    "credit_note": {
                        "id": "cn_1",
                        "status": "voided",
                        "voided_at": 1_702_500_000,
                    }
                },
            )
        )
        assert events[0].type == "credit_note.voided"


# ── Signature verification (HTTP Basic Auth) ─────────────────────────────


class TestVerifySignature:
    def test_no_config_falls_through(self, connector: ChargebeeConnector):
        # Lenient accept when neither user nor pass is configured — same
        # pattern as Stripe / QuickBooks. Production deployments must
        # configure both.
        assert connector.verify_signature(b"body", "Basic anything") is True

    def test_correct_basic_auth_accepted(self):
        config = {"webhook_username": "tidemill", "webhook_password": "s3cret"}
        conn = ChargebeeConnector(source_id=SRC, config=config)
        token = base64.b64encode(b"tidemill:s3cret").decode()
        assert conn.verify_signature(b"body", f"Basic {token}") is True

    def test_wrong_password_rejected(self):
        config = {"webhook_username": "tidemill", "webhook_password": "s3cret"}
        conn = ChargebeeConnector(source_id=SRC, config=config)
        token = base64.b64encode(b"tidemill:wrong").decode()
        assert conn.verify_signature(b"body", f"Basic {token}") is False

    def test_missing_basic_prefix_rejected(self):
        config = {"webhook_username": "tidemill", "webhook_password": "s3cret"}
        conn = ChargebeeConnector(source_id=SRC, config=config)
        token = base64.b64encode(b"tidemill:s3cret").decode()
        assert conn.verify_signature(b"body", token) is False  # missing "Basic " prefix

    def test_garbage_header_rejected(self):
        config = {"webhook_username": "tidemill", "webhook_password": "s3cret"}
        conn = ChargebeeConnector(source_id=SRC, config=config)
        assert conn.verify_signature(b"body", "Basic !!!not-b64!!!") is False


# ── Unknown event types ──────────────────────────────────────────────────


class TestUnknownEvents:
    def test_unknown_type_returns_empty(self, connector: ChargebeeConnector):
        events = connector.translate(_wh("widgetized_synergy", {"some": "thing"}))
        assert events == []
