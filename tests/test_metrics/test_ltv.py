"""Tests for LtvMetric.handle_event — SQLite in-memory."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tidemill.metrics.ltv.metric import LtvMetric

from .conftest import T0, T1, make_evt


class TestLtvHandler:
    @pytest.fixture
    def metric(self, db) -> LtvMetric:
        m = LtvMetric()
        m.init(db=db)
        return m

    @pytest.mark.asyncio
    async def test_invoice_paid_creates_row(self, metric, db):
        event = make_evt(
            "invoice.paid",
            {"external_id": "inv_1", "amount_cents": 7900, "currency": "USD"},
        )
        await metric.handle_event(event)
        await db.commit()

        row = (
            await db.execute(
                text(
                    "SELECT amount_cents, amount_base_cents, currency, customer_id"
                    " FROM metric_ltv_invoice WHERE customer_id = 'cus_1'"
                )
            )
        ).fetchone()
        assert row is not None
        assert row[0] == 7900
        assert row[1] == 7900  # USD → USD passthrough
        assert row[2] == "USD"
        assert row[3] == "cus_1"

    @pytest.mark.asyncio
    async def test_idempotent_replay(self, metric, db):
        """Processing the same event twice → one row."""
        event = make_evt(
            "invoice.paid",
            {"external_id": "inv_1", "amount_cents": 7900, "currency": "USD"},
        )
        await metric.handle_event(event)
        await db.commit()
        await metric.handle_event(event)
        await db.commit()

        count = (await db.execute(text("SELECT COUNT(*) FROM metric_ltv_invoice"))).scalar()
        assert count == 1

    @pytest.mark.asyncio
    async def test_multiple_invoices_accumulated(self, metric, db):
        """Multiple paid invoices from same customer → multiple rows."""
        await metric.handle_event(
            make_evt(
                "invoice.paid",
                {"external_id": "inv_1", "amount_cents": 7900, "currency": "USD"},
                occurred_at=T0,
            )
        )
        await metric.handle_event(
            make_evt(
                "invoice.paid",
                {"external_id": "inv_2", "amount_cents": 7900, "currency": "USD"},
                external_id="inv_2",
                occurred_at=T1,
            )
        )
        await db.commit()

        count = (
            await db.execute(
                text("SELECT COUNT(*) FROM metric_ltv_invoice WHERE customer_id = 'cus_1'")
            )
        ).scalar()
        assert count == 2

        total = (
            await db.execute(
                text(
                    "SELECT SUM(amount_base_cents) FROM metric_ltv_invoice"
                    " WHERE customer_id = 'cus_1'"
                )
            )
        ).scalar()
        assert total == 15800

    @pytest.mark.asyncio
    async def test_different_customers(self, metric, db):
        await metric.handle_event(
            make_evt(
                "invoice.paid",
                {"external_id": "inv_1", "amount_cents": 5000, "currency": "USD"},
                customer_id="cus_1",
            )
        )
        await metric.handle_event(
            make_evt(
                "invoice.paid",
                {"external_id": "inv_2", "amount_cents": 9000, "currency": "USD"},
                customer_id="cus_2",
                external_id="inv_2",
            )
        )
        await db.commit()

        rows = (
            await db.execute(
                text(
                    "SELECT customer_id, amount_cents FROM metric_ltv_invoice ORDER BY customer_id"
                )
            )
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][0] == "cus_1"
        assert rows[0][1] == 5000
        assert rows[1][0] == "cus_2"
        assert rows[1][1] == 9000

    @pytest.mark.asyncio
    async def test_currency_default(self, metric, db):
        """Missing currency defaults to USD."""
        event = make_evt(
            "invoice.paid",
            {"external_id": "inv_1", "amount_cents": 5000},
        )
        await metric.handle_event(event)
        await db.commit()

        row = (
            await db.execute(
                text("SELECT currency FROM metric_ltv_invoice WHERE customer_id = 'cus_1'")
            )
        ).fetchone()
        assert row[0] == "USD"
