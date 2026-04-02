"""Integration tests for ChurnMetric against real PostgreSQL."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from subscriptions.metrics.churn.metric import ChurnMetric

from .conftest import SRC_PG, T1, T2, make_evt

pytestmark = pytest.mark.integration

_e = lambda *a, **kw: make_evt(*a, source_id=SRC_PG, **kw)  # noqa: E731


class TestChurnPg:
    @pytest.fixture
    def metric(self, pg_db) -> ChurnMetric:
        m = ChurnMetric()
        m.init(db=pg_db)
        return m

    async def test_customer_state_tracking(self, metric, pg_db):
        await metric.handle_event(_e("subscription.activated", {"external_id": "sub_1"}))
        await metric.handle_event(
            _e("subscription.activated", {"external_id": "sub_2"}, external_id="sub_2")
        )
        await pg_db.commit()

        row = (
            await pg_db.execute(
                text(
                    "SELECT active_subscriptions"
                    " FROM metric_churn_customer_state"
                    " WHERE customer_id = 'cus_1'"
                )
            )
        ).fetchone()
        assert row[0] == 2

        # Churn one
        await metric.handle_event(
            _e(
                "subscription.churned",
                {"external_id": "sub_1", "prev_mrr_cents": 5000},
                occurred_at=T1,
            )
        )
        await pg_db.commit()

        row = (
            await pg_db.execute(
                text(
                    "SELECT active_subscriptions, churned_at"
                    " FROM metric_churn_customer_state"
                    " WHERE customer_id = 'cus_1'"
                )
            )
        ).fetchone()
        assert row[0] == 1
        assert row[1] is None

        # Churn second → logo churn
        await metric.handle_event(
            _e(
                "subscription.churned",
                {"external_id": "sub_2", "prev_mrr_cents": 3000},
                external_id="sub_2",
                occurred_at=T2,
            )
        )
        await pg_db.commit()

        row = (
            await pg_db.execute(
                text(
                    "SELECT active_subscriptions, churned_at"
                    " FROM metric_churn_customer_state"
                    " WHERE customer_id = 'cus_1'"
                )
            )
        ).fetchone()
        assert row[0] == 0
        assert row[1] is not None

        logo = (
            await pg_db.execute(
                text("SELECT COUNT(*) FROM metric_churn_event WHERE churn_type = 'logo'")
            )
        ).scalar()
        assert logo == 1

        revenue = (
            await pg_db.execute(
                text("SELECT COUNT(*) FROM metric_churn_event WHERE churn_type = 'revenue'")
            )
        ).scalar()
        assert revenue == 2

    async def test_reactivation_clears_churned(self, metric, pg_db):
        await metric.handle_event(_e("subscription.activated", {"external_id": "sub_1"}))
        await metric.handle_event(
            _e(
                "subscription.churned",
                {"external_id": "sub_1", "prev_mrr_cents": 5000},
                occurred_at=T1,
            )
        )
        await pg_db.commit()

        await metric.handle_event(
            _e("subscription.reactivated", {"external_id": "sub_1"}, occurred_at=T2)
        )
        await pg_db.commit()

        row = (
            await pg_db.execute(
                text(
                    "SELECT active_subscriptions, churned_at"
                    " FROM metric_churn_customer_state"
                    " WHERE customer_id = 'cus_1'"
                )
            )
        ).fetchone()
        assert row[0] == 1
        assert row[1] is None
