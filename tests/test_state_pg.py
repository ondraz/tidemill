"""Integration tests for state handler against real PostgreSQL.

Verifies ON CONFLICT behaviour, TIMESTAMPTZ handling, and index usage
that SQLite cannot fully replicate.

Run with:  pytest -m integration
Requires:  TEST_DATABASE_URL or a local PostgreSQL named subscriptions_test
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from subscriptions.events import Event, make_event_id
from subscriptions.state import handle_state_event

pytestmark = pytest.mark.integration

SRC = "src_pg"
T0 = datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC)
T1 = datetime(2026, 2, 15, 10, 30, 0, tzinfo=UTC)
T2 = datetime(2026, 3, 15, 10, 30, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
async def _seed_source(pg_db):
    """Every state-handler test needs a connector_source row for FKs."""
    await pg_db.execute(
        text(
            "INSERT INTO connector_source (id, type, name, created_at)"
            " VALUES (:id, 'test', 'test', :now)"
            " ON CONFLICT (id) DO NOTHING"
        ),
        {"id": SRC, "now": T0},
    )
    await pg_db.commit()


def _evt(
    event_type: str,
    payload: dict,
    *,
    customer_id: str = "cus_ext_1",
    external_id: str = "ext_1",
    occurred_at: datetime = T0,
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


class TestEventLogPg:
    async def test_insert_and_idempotent(self, pg_db):
        event = _evt("customer.created", {"external_id": "cus_ext_1", "name": "PG"})
        await handle_state_event(pg_db, event)
        await pg_db.commit()

        # Second time — ON CONFLICT (id) DO NOTHING
        await handle_state_event(pg_db, event)
        await pg_db.commit()

        count = (await pg_db.execute(text("SELECT COUNT(*) FROM event_log"))).scalar()
        assert count == 1

    async def test_timestamptz_preserved(self, pg_db):
        event = _evt("customer.created", {"external_id": "cus_ext_1", "name": "PG"})
        await handle_state_event(pg_db, event)
        await pg_db.commit()

        row = (
            await pg_db.execute(
                text("SELECT occurred_at FROM event_log WHERE id = :id"), {"id": event.id}
            )
        ).fetchone()
        assert row is not None
        assert row[0] == T0


# ── customer ─────────────────────────────────────────────────────────────


class TestCustomerPg:
    async def test_upsert_on_conflict(self, pg_db):
        """ON CONFLICT ON CONSTRAINT uq_customer_source DO UPDATE works natively."""
        payload = {"external_id": "cus_ext_1", "name": "Alice", "email": "a@e.co"}
        await handle_state_event(pg_db, _evt("customer.created", payload))
        await pg_db.commit()

        # Upsert with new name
        await handle_state_event(
            pg_db,
            _evt(
                "customer.updated",
                {"external_id": "cus_ext_1", "name": "Alice V2"},
                occurred_at=T1,
            ),
        )
        await pg_db.commit()

        row = (
            await pg_db.execute(
                text("SELECT name, email FROM customer WHERE source_id = :s AND external_id = :e"),
                {"s": SRC, "e": "cus_ext_1"},
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "Alice V2"
        assert row[1] == "a@e.co"  # preserved via COALESCE

    async def test_delete(self, pg_db):
        await handle_state_event(
            pg_db, _evt("customer.created", {"external_id": "cus_ext_1", "name": "X"})
        )
        await pg_db.commit()
        await handle_state_event(pg_db, _evt("customer.deleted", {"external_id": "cus_ext_1"}))
        await pg_db.commit()

        count = (
            await pg_db.execute(
                text("SELECT COUNT(*) FROM customer WHERE source_id = :s"), {"s": SRC}
            )
        ).scalar()
        assert count == 0


# ── subscription lifecycle ───────────────────────────────────────────────


async def _seed(pg_db) -> None:  # noqa: RUF029
    """Seed customer + plan for FK satisfaction."""
    await handle_state_event(
        pg_db, _evt("customer.created", {"external_id": "cus_ext_1", "name": "Cust"})
    )
    await pg_db.execute(
        text(
            "INSERT INTO plan (id, source_id, external_id, name,"
            " interval, interval_count, amount_cents, created_at)"
            " VALUES ('p1', :s, 'plan_1', 'Basic', 'month', 1, 5000, :t)"
        ),
        {"s": SRC, "t": T0},
    )
    await pg_db.commit()


class TestSubscriptionLifecyclePg:
    async def test_full_lifecycle(self, pg_db):
        """create → activate → change → cancel → churn → reactivate on real PG."""
        await _seed(pg_db)

        # Create (trialing)
        await handle_state_event(
            pg_db,
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
        await pg_db.commit()

        row = (
            await pg_db.execute(
                text("SELECT status FROM subscription WHERE external_id = 'sub_1'")
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "trialing"

        # Activate
        await handle_state_event(
            pg_db,
            _evt(
                "subscription.activated",
                {"external_id": "sub_1", "mrr_cents": 5000},
                external_id="sub_1",
                occurred_at=T1,
            ),
        )
        await pg_db.commit()

        row = (
            await pg_db.execute(
                text("SELECT status, mrr_cents FROM subscription WHERE external_id = 'sub_1'")
            )
        ).fetchone()
        assert row[0] == "active"
        assert row[1] == 5000

        # Cancel (pending)
        await handle_state_event(
            pg_db,
            _evt(
                "subscription.canceled",
                {"external_id": "sub_1", "mrr_cents": 5000},
                external_id="sub_1",
                occurred_at=T1,
            ),
        )
        await pg_db.commit()

        row = (
            await pg_db.execute(
                text(
                    "SELECT status, cancel_at_period_end"
                    " FROM subscription WHERE external_id = 'sub_1'"
                )
            )
        ).fetchone()
        assert row[0] == "canceled"
        assert row[1] is True

        # Churn
        await handle_state_event(
            pg_db,
            _evt(
                "subscription.churned",
                {"external_id": "sub_1", "prev_mrr_cents": 5000},
                external_id="sub_1",
                occurred_at=T2,
            ),
        )
        await pg_db.commit()

        row = (
            await pg_db.execute(
                text(
                    "SELECT status, mrr_cents, ended_at"
                    " FROM subscription WHERE external_id = 'sub_1'"
                )
            )
        ).fetchone()
        assert row[0] == "canceled"
        assert row[1] == 0
        assert row[2] is not None

        # Reactivate
        await handle_state_event(
            pg_db,
            _evt(
                "subscription.reactivated",
                {"external_id": "sub_1", "mrr_cents": 5000},
                external_id="sub_1",
                occurred_at=T2,
            ),
        )
        await pg_db.commit()

        row = (
            await pg_db.execute(
                text(
                    "SELECT status, mrr_cents, ended_at"
                    " FROM subscription WHERE external_id = 'sub_1'"
                )
            )
        ).fetchone()
        assert row[0] == "active"
        assert row[1] == 5000
        assert row[2] is None

    async def test_upsert_idempotent(self, pg_db):
        """Same subscription.created twice → one row via ON CONFLICT."""
        await _seed(pg_db)
        payload = {
            "external_id": "sub_1",
            "customer_external_id": "cus_ext_1",
            "plan_external_id": "plan_1",
            "status": "active",
            "mrr_cents": 5000,
            "currency": "USD",
            "quantity": 1,
        }
        await handle_state_event(pg_db, _evt("subscription.created", payload, external_id="sub_1"))
        await pg_db.commit()
        await handle_state_event(pg_db, _evt("subscription.created", payload, external_id="sub_1"))
        await pg_db.commit()

        count = (
            await pg_db.execute(
                text("SELECT COUNT(*) FROM subscription WHERE source_id = :s"), {"s": SRC}
            )
        ).scalar()
        assert count == 1


# ── invoice + payment ────────────────────────────────────────────────────


class TestInvoicePaymentPg:
    async def test_invoice_create_and_pay(self, pg_db):
        await handle_state_event(
            pg_db,
            _evt(
                "invoice.created",
                {
                    "external_id": "inv_1",
                    "customer_external_id": "cus_ext_1",
                    "subscription_external_id": "",
                    "status": "open",
                    "currency": "USD",
                    "subtotal_cents": 5000,
                    "tax_cents": 500,
                    "total_cents": 5500,
                },
                external_id="inv_1",
            ),
        )
        await pg_db.commit()

        row = (
            await pg_db.execute(
                text("SELECT status, total_cents FROM invoice WHERE external_id = 'inv_1'")
            )
        ).fetchone()
        assert row[0] == "open"
        assert row[1] == 5500

        await handle_state_event(
            pg_db,
            _evt(
                "invoice.paid",
                {"external_id": "inv_1", "amount_cents": 5500},
                external_id="inv_1",
                occurred_at=T1,
            ),
        )
        await pg_db.commit()

        row = (
            await pg_db.execute(
                text("SELECT status, paid_at FROM invoice WHERE external_id = 'inv_1'")
            )
        ).fetchone()
        assert row[0] == "paid"
        assert row[1] is not None

    async def test_payment_upsert(self, pg_db):
        """Failed then succeeded → final status is 'succeeded' via ON CONFLICT."""
        await handle_state_event(
            pg_db,
            _evt(
                "payment.failed",
                {
                    "external_id": "pi_1",
                    "customer_external_id": "cus_ext_1",
                    "invoice_external_id": "",
                    "amount_cents": 5000,
                    "failure_reason": "declined",
                    "attempt_count": 1,
                },
                external_id="pi_1",
            ),
        )
        await pg_db.commit()

        await handle_state_event(
            pg_db,
            _evt(
                "payment.succeeded",
                {
                    "external_id": "pi_1",
                    "customer_external_id": "cus_ext_1",
                    "invoice_external_id": "",
                    "amount_cents": 5000,
                    "currency": "USD",
                },
                external_id="pi_1",
                occurred_at=T1,
            ),
        )
        await pg_db.commit()

        row = (
            await pg_db.execute(text("SELECT status FROM payment WHERE external_id = 'pi_1'"))
        ).fetchone()
        assert row[0] == "succeeded"
