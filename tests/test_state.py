"""Tests for state.handle_state_event — SQLite in-memory, no PostgreSQL.

Tests: customer create/update/delete, subscription lifecycle
(create → activate → change → churn → reactivate), event_log idempotency.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from subscriptions.events import Event, make_event_id
from subscriptions.state import handle_state_event

SRC = "src_1"
NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 2, 15, 12, 0, 0, tzinfo=UTC)


def _evt(
    event_type: str,
    payload: dict,
    *,
    customer_id: str = "cus_ext_1",
    external_id: str = "ext_1",
    occurred_at: datetime = NOW,
) -> Event:
    return Event(
        id=make_event_id(SRC, event_type, external_id),
        source_id=SRC,
        type=event_type,
        occurred_at=occurred_at,
        published_at=occurred_at,
        customer_id=customer_id,
        payload=payload,
    )


# ── event_log ────────────────────────────────────────────────────────────


class TestEventLog:
    @pytest.mark.asyncio
    async def test_insert(self, db):
        event = _evt("customer.created", {"external_id": "cus_ext_1", "name": "Alice"})
        await handle_state_event(db, event)
        await db.commit()

        rows = (await db.execute(text("SELECT id, type FROM event_log"))).fetchall()
        assert len(rows) == 1
        assert rows[0][1] == "customer.created"

    @pytest.mark.asyncio
    async def test_idempotent(self, db):
        """Processing the same event twice → one row."""
        event = _evt("customer.created", {"external_id": "cus_ext_1", "name": "Alice"})
        await handle_state_event(db, event)
        await db.commit()
        await handle_state_event(db, event)
        await db.commit()

        rows = (await db.execute(text("SELECT COUNT(*) FROM event_log"))).scalar()
        assert rows == 1


# ── customer ─────────────────────────────────────────────────────────────


class TestCustomerHandler:
    @pytest.mark.asyncio
    async def test_create(self, db):
        event = _evt(
            "customer.created",
            {
                "external_id": "cus_ext_1",
                "name": "Alice",
                "email": "alice@example.com",
                "currency": "USD",
                "metadata": {},
            },
        )
        await handle_state_event(db, event)
        await db.commit()

        row = (
            await db.execute(
                text("SELECT name, email, currency FROM customer WHERE external_id = 'cus_ext_1'")
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "Alice"
        assert row[1] == "alice@example.com"

    @pytest.mark.asyncio
    async def test_update(self, db):
        # Create first
        await handle_state_event(
            db,
            _evt(
                "customer.created",
                {
                    "external_id": "cus_ext_1",
                    "name": "Alice",
                    "email": "a@e.co",
                },
            ),
        )
        await db.commit()

        # Then update
        await handle_state_event(
            db,
            _evt(
                "customer.updated",
                {"external_id": "cus_ext_1", "name": "Alice Updated"},
                occurred_at=LATER,
            ),
        )
        await db.commit()

        row = (
            await db.execute(text("SELECT name FROM customer WHERE external_id = 'cus_ext_1'"))
        ).fetchone()
        assert row is not None
        assert row[0] == "Alice Updated"

    @pytest.mark.asyncio
    async def test_delete(self, db):
        await handle_state_event(
            db,
            _evt(
                "customer.created",
                {
                    "external_id": "cus_ext_1",
                    "name": "Alice",
                },
            ),
        )
        await db.commit()

        await handle_state_event(
            db,
            _evt(
                "customer.deleted",
                {
                    "external_id": "cus_ext_1",
                },
            ),
        )
        await db.commit()

        count = (
            await db.execute(text("SELECT COUNT(*) FROM customer WHERE external_id = 'cus_ext_1'"))
        ).scalar()
        assert count == 0

    @pytest.mark.asyncio
    async def test_upsert_idempotent(self, db):
        """Creating the same customer twice doesn't duplicate."""
        payload = {"external_id": "cus_ext_1", "name": "Alice"}
        await handle_state_event(db, _evt("customer.created", payload))
        await db.commit()
        await handle_state_event(db, _evt("customer.created", payload))
        await db.commit()

        count = (await db.execute(text("SELECT COUNT(*) FROM customer"))).scalar()
        assert count == 1


# ── subscription lifecycle ───────────────────────────────────────────────


class TestSubscriptionLifecycle:
    async def _seed_refs(self, db):
        """Create customer + plan so subscription FKs don't fail."""
        await handle_state_event(
            db,
            _evt(
                "customer.created",
                {
                    "external_id": "cus_ext_1",
                    "name": "Test Customer",
                },
            ),
        )
        # Seed plan directly since there's no plan event handler.
        await db.execute(
            text(
                "INSERT INTO plan (id, source_id, external_id, name,"
                ' "interval", interval_count, amount_cents, created_at)'
                " VALUES ('plan_id_1', :src, 'plan_1', 'Basic', 'month', 1, 5000, :now)"
            ),
            {"src": SRC, "now": NOW},
        )
        await db.execute(
            text(
                "INSERT INTO plan (id, source_id, external_id, name,"
                ' "interval", interval_count, amount_cents, created_at)'
                " VALUES ('plan_id_2', :src, 'plan_2', 'Pro', 'month', 1, 9900, :now)"
            ),
            {"src": SRC, "now": NOW},
        )
        await db.commit()

    @pytest.mark.asyncio
    async def test_create(self, db):
        await self._seed_refs(db)

        event = _evt(
            "subscription.created",
            {
                "external_id": "sub_1",
                "customer_external_id": "cus_ext_1",
                "plan_external_id": "plan_1",
                "status": "active",
                "mrr_cents": 5000,
                "currency": "USD",
                "quantity": 1,
            },
            external_id="sub_1",
        )
        await handle_state_event(db, event)
        await db.commit()

        row = (
            await db.execute(
                text(
                    "SELECT status, mrr_cents, currency FROM subscription"
                    " WHERE external_id = 'sub_1'"
                )
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "active"
        assert row[1] == 5000

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, db):
        """create → activate → change → churn → reactivate."""
        await self._seed_refs(db)

        # Create
        await handle_state_event(
            db,
            _evt(
                "subscription.created",
                {
                    "external_id": "sub_1",
                    "customer_external_id": "cus_ext_1",
                    "plan_external_id": "plan_1",
                    "status": "trialing",
                    "mrr_cents": 0,
                    "currency": "USD",
                    "quantity": 1,
                },
                external_id="sub_1",
            ),
        )
        await db.commit()

        row = (
            await db.execute(
                text("SELECT status, mrr_cents FROM subscription WHERE external_id = 'sub_1'")
            )
        ).fetchone()
        assert row[0] == "trialing"
        assert row[1] == 0

        # Activate
        await handle_state_event(
            db,
            _evt(
                "subscription.activated",
                {"external_id": "sub_1", "mrr_cents": 5000},
                external_id="sub_1",
                occurred_at=datetime(2026, 1, 20, tzinfo=UTC),
            ),
        )
        await db.commit()

        row = (
            await db.execute(
                text("SELECT status, mrr_cents FROM subscription WHERE external_id = 'sub_1'")
            )
        ).fetchone()
        assert row[0] == "active"
        assert row[1] == 5000

        # Change (upgrade)
        await handle_state_event(
            db,
            _evt(
                "subscription.changed",
                {
                    "external_id": "sub_1",
                    "new_plan_external_id": "plan_2",
                    "new_mrr_cents": 9900,
                    "new_quantity": 1,
                },
                external_id="sub_1",
                occurred_at=datetime(2026, 2, 1, tzinfo=UTC),
            ),
        )
        await db.commit()

        row = (
            await db.execute(
                text("SELECT mrr_cents FROM subscription WHERE external_id = 'sub_1'")
            )
        ).fetchone()
        assert row[0] == 9900

        # Churn
        await handle_state_event(
            db,
            _evt(
                "subscription.churned",
                {"external_id": "sub_1", "prev_mrr_cents": 9900},
                external_id="sub_1",
                occurred_at=datetime(2026, 3, 1, tzinfo=UTC),
            ),
        )
        await db.commit()

        row = (
            await db.execute(
                text(
                    "SELECT status, mrr_cents, ended_at FROM subscription"
                    " WHERE external_id = 'sub_1'"
                )
            )
        ).fetchone()
        assert row[0] == "canceled"
        assert row[1] == 0
        assert row[2] is not None

        # Reactivate
        await handle_state_event(
            db,
            _evt(
                "subscription.reactivated",
                {"external_id": "sub_1", "mrr_cents": 5000},
                external_id="sub_1",
                occurred_at=datetime(2026, 4, 1, tzinfo=UTC),
            ),
        )
        await db.commit()

        row = (
            await db.execute(
                text(
                    "SELECT status, mrr_cents, ended_at FROM subscription"
                    " WHERE external_id = 'sub_1'"
                )
            )
        ).fetchone()
        assert row[0] == "active"
        assert row[1] == 5000
        assert row[2] is None


# ── invoice lifecycle ────────────────────────────────────────────────────


class TestInvoiceHandler:
    @pytest.mark.asyncio
    async def test_create_and_pay(self, db):
        # Create
        await handle_state_event(
            db,
            _evt(
                "invoice.created",
                {
                    "external_id": "inv_1",
                    "customer_external_id": "cus_ext_1",
                    "subscription_external_id": "sub_1",
                    "status": "open",
                    "currency": "USD",
                    "subtotal_cents": 5000,
                    "tax_cents": 0,
                    "total_cents": 5000,
                },
                external_id="inv_1",
            ),
        )
        await db.commit()

        row = (
            await db.execute(
                text("SELECT status, total_cents FROM invoice WHERE external_id = 'inv_1'")
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "open"
        assert row[1] == 5000

        # Pay
        await handle_state_event(
            db,
            _evt(
                "invoice.paid",
                {"external_id": "inv_1", "amount_cents": 5000},
                external_id="inv_1",
                occurred_at=LATER,
            ),
        )
        await db.commit()

        row = (
            await db.execute(
                text("SELECT status, paid_at FROM invoice WHERE external_id = 'inv_1'")
            )
        ).fetchone()
        assert row[0] == "paid"
        assert row[1] is not None


# ── payment lifecycle ────────────────────────────────────────────────────


class TestPaymentHandler:
    @pytest.mark.asyncio
    async def test_succeeded(self, db):
        await handle_state_event(
            db,
            _evt(
                "payment.succeeded",
                {
                    "external_id": "pi_1",
                    "customer_external_id": "cus_ext_1",
                    "invoice_external_id": "inv_1",
                    "amount_cents": 5000,
                    "currency": "USD",
                    "payment_method_type": "card",
                },
                external_id="pi_1",
            ),
        )
        await db.commit()

        row = (
            await db.execute(
                text("SELECT status, amount_cents FROM payment WHERE external_id = 'pi_1'")
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "succeeded"
        assert row[1] == 5000

    @pytest.mark.asyncio
    async def test_failed_then_refund(self, db):
        # Failed
        await handle_state_event(
            db,
            _evt(
                "payment.failed",
                {
                    "external_id": "pi_2",
                    "customer_external_id": "cus_ext_1",
                    "invoice_external_id": "inv_1",
                    "amount_cents": 5000,
                    "failure_reason": "Card declined",
                    "attempt_count": 1,
                },
                external_id="pi_2",
            ),
        )
        await db.commit()

        row = (
            await db.execute(
                text("SELECT status, failure_reason FROM payment WHERE external_id = 'pi_2'")
            )
        ).fetchone()
        assert row[0] == "failed"
        assert row[1] == "Card declined"

        # Then succeeded (upsert)
        await handle_state_event(
            db,
            _evt(
                "payment.succeeded",
                {
                    "external_id": "pi_2",
                    "customer_external_id": "cus_ext_1",
                    "invoice_external_id": "inv_1",
                    "amount_cents": 5000,
                    "currency": "USD",
                },
                external_id="pi_2",
                occurred_at=LATER,
            ),
        )
        await db.commit()

        row = (
            await db.execute(text("SELECT status FROM payment WHERE external_id = 'pi_2'"))
        ).fetchone()
        assert row[0] == "succeeded"
