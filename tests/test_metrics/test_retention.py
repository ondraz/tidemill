"""Tests for RetentionMetric.handle_event — SQLite in-memory."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from subscriptions.metrics.retention.metric import RetentionMetric

from .conftest import T0, T1, T2, make_evt


class TestRetentionHandler:
    @pytest.fixture
    def metric(self, db) -> RetentionMetric:
        m = RetentionMetric()
        m.init(db=db)
        return m

    @pytest.mark.asyncio
    async def test_cohort_assigned_on_created(self, metric, db):
        await metric.handle_event(make_evt("subscription.created", {"external_id": "sub_1"}))
        await db.commit()

        row = (
            await db.execute(
                text(
                    "SELECT cohort_month FROM metric_retention_cohort WHERE customer_id = 'cus_1'"
                )
            )
        ).fetchone()
        assert row is not None
        assert str(row[0]) == "2026-01-01"

    @pytest.mark.asyncio
    async def test_cohort_not_overwritten_on_reactivation(self, metric, db):
        """Cohort month stays as first activation, not reactivation."""
        await metric.handle_event(
            make_evt("subscription.created", {"external_id": "sub_1"}, occurred_at=T0)
        )
        await db.commit()

        await metric.handle_event(
            make_evt("subscription.reactivated", {"external_id": "sub_1"}, occurred_at=T2)
        )
        await db.commit()

        row = (
            await db.execute(
                text(
                    "SELECT cohort_month FROM metric_retention_cohort WHERE customer_id = 'cus_1'"
                )
            )
        ).fetchone()
        assert str(row[0]) == "2026-01-01"

    @pytest.mark.asyncio
    async def test_activity_recorded(self, metric, db):
        await metric.handle_event(make_evt("subscription.created", {"external_id": "sub_1"}))
        await db.commit()

        row = (
            await db.execute(
                text(
                    "SELECT active_month FROM metric_retention_activity"
                    " WHERE customer_id = 'cus_1'"
                )
            )
        ).fetchone()
        assert row is not None
        assert str(row[0]) == "2026-01-01"

    @pytest.mark.asyncio
    async def test_activity_multiple_months(self, metric, db):
        """Events in different months → separate activity rows."""
        await metric.handle_event(
            make_evt("subscription.created", {"external_id": "sub_1"}, occurred_at=T0)
        )
        await metric.handle_event(
            make_evt("subscription.activated", {"external_id": "sub_1"}, occurred_at=T1)
        )
        await metric.handle_event(
            make_evt("subscription.reactivated", {"external_id": "sub_1"}, occurred_at=T2)
        )
        await db.commit()

        count = (
            await db.execute(
                text("SELECT COUNT(*) FROM metric_retention_activity WHERE customer_id = 'cus_1'")
            )
        ).scalar()
        assert count == 3

    @pytest.mark.asyncio
    async def test_activity_idempotent(self, metric, db):
        """Same month twice → one activity row."""
        event = make_evt("subscription.created", {"external_id": "sub_1"})
        await metric.handle_event(event)
        await db.commit()
        await metric.handle_event(event)
        await db.commit()

        count = (
            await db.execute(
                text("SELECT COUNT(*) FROM metric_retention_activity WHERE customer_id = 'cus_1'")
            )
        ).scalar()
        assert count == 1
