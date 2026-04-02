"""Integration tests for RetentionMetric against real PostgreSQL."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text

from subscriptions.metrics.retention.metric import RetentionMetric

from .conftest import SRC_PG, T0, T1, T2, make_evt

pytestmark = pytest.mark.integration

_e = lambda *a, **kw: make_evt(*a, source_id=SRC_PG, **kw)  # noqa: E731


class TestRetentionPg:
    @pytest.fixture
    def metric(self, pg_db) -> RetentionMetric:
        m = RetentionMetric()
        m.init(db=pg_db)
        return m

    async def test_cohort_and_activity(self, metric, pg_db):
        await metric.handle_event(
            _e("subscription.created", {"external_id": "sub_1"}, occurred_at=T0)
        )
        await metric.handle_event(
            _e("subscription.activated", {"external_id": "sub_1"}, occurred_at=T1)
        )
        await metric.handle_event(
            _e("subscription.reactivated", {"external_id": "sub_1"}, occurred_at=T2)
        )
        await pg_db.commit()

        row = (
            await pg_db.execute(
                text(
                    "SELECT cohort_month FROM metric_retention_cohort WHERE customer_id = 'cus_1'"
                )
            )
        ).fetchone()
        assert row[0] == date(2026, 1, 1)

        count = (
            await pg_db.execute(
                text("SELECT COUNT(*) FROM metric_retention_activity WHERE customer_id = 'cus_1'")
            )
        ).scalar()
        assert count == 3

    async def test_cohort_not_overwritten(self, metric, pg_db):
        """ON CONFLICT DO NOTHING preserves original cohort_month on PG."""
        await metric.handle_event(
            _e("subscription.created", {"external_id": "sub_1"}, occurred_at=T0)
        )
        await pg_db.commit()

        await metric.handle_event(
            _e("subscription.activated", {"external_id": "sub_1"}, occurred_at=T2)
        )
        await pg_db.commit()

        row = (
            await pg_db.execute(
                text(
                    "SELECT cohort_month FROM metric_retention_cohort WHERE customer_id = 'cus_1'"
                )
            )
        ).fetchone()
        assert row[0] == date(2026, 1, 1)

    async def test_activity_idempotent(self, metric, pg_db):
        event = _e("subscription.created", {"external_id": "sub_1"}, occurred_at=T0)
        await metric.handle_event(event)
        await pg_db.commit()
        await metric.handle_event(event)
        await pg_db.commit()

        count = (
            await pg_db.execute(
                text("SELECT COUNT(*) FROM metric_retention_activity WHERE customer_id = 'cus_1'")
            )
        ).scalar()
        assert count == 1
