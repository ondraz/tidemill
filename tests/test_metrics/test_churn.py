"""Tests for ChurnMetric.handle_event — SQLite in-memory."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from subscriptions.metrics.churn.metric import ChurnMetric

from .conftest import T1, T2, make_evt


class TestChurnHandler:
    @pytest.fixture
    def metric(self, db) -> ChurnMetric:
        m = ChurnMetric()
        m.init(db=db)
        return m

    @pytest.mark.asyncio
    async def test_active_subscription_increments(self, metric, db):
        await metric.handle_event(make_evt("subscription.activated", {"external_id": "sub_1"}))
        await db.commit()

        row = (
            await db.execute(
                text(
                    "SELECT active_subscriptions, first_active_at"
                    " FROM metric_churn_customer_state"
                    " WHERE customer_id = 'cus_1'"
                )
            )
        ).fetchone()
        assert row is not None
        assert row[0] == 1
        assert row[1] is not None

    @pytest.mark.asyncio
    async def test_multiple_subs_increment(self, metric, db):
        await metric.handle_event(make_evt("subscription.activated", {"external_id": "sub_1"}))
        await metric.handle_event(
            make_evt("subscription.activated", {"external_id": "sub_2"}, external_id="sub_2")
        )
        await db.commit()

        row = (
            await db.execute(
                text(
                    "SELECT active_subscriptions"
                    " FROM metric_churn_customer_state"
                    " WHERE customer_id = 'cus_1'"
                )
            )
        ).fetchone()
        assert row[0] == 2

    @pytest.mark.asyncio
    async def test_churned_decrements_and_sets_churned_at(self, metric, db):
        await metric.handle_event(make_evt("subscription.activated", {"external_id": "sub_1"}))
        await db.commit()

        await metric.handle_event(
            make_evt(
                "subscription.churned",
                {"external_id": "sub_1", "prev_mrr_cents": 5000},
                occurred_at=T1,
            )
        )
        await db.commit()

        row = (
            await db.execute(
                text(
                    "SELECT active_subscriptions, churned_at"
                    " FROM metric_churn_customer_state"
                    " WHERE customer_id = 'cus_1'"
                )
            )
        ).fetchone()
        assert row[0] == 0
        assert row[1] is not None

    @pytest.mark.asyncio
    async def test_logo_churn_event(self, metric, db):
        """When last sub churns → logo churn event."""
        await metric.handle_event(make_evt("subscription.activated", {"external_id": "sub_1"}))
        await db.commit()

        await metric.handle_event(
            make_evt(
                "subscription.churned",
                {"external_id": "sub_1", "prev_mrr_cents": 5000},
                occurred_at=T1,
            )
        )
        await db.commit()

        logo = (
            await db.execute(
                text(
                    "SELECT churn_type, mrr_cents FROM metric_churn_event"
                    " WHERE churn_type = 'logo'"
                )
            )
        ).fetchone()
        assert logo is not None
        assert logo[1] == 5000

    @pytest.mark.asyncio
    async def test_revenue_churn_event_always(self, metric, db):
        """Revenue churn event is created on every subscription.churned."""
        await metric.handle_event(make_evt("subscription.activated", {"external_id": "sub_1"}))
        await db.commit()

        await metric.handle_event(
            make_evt(
                "subscription.churned",
                {"external_id": "sub_1", "prev_mrr_cents": 3000},
                occurred_at=T1,
            )
        )
        await db.commit()

        rev = (
            await db.execute(
                text(
                    "SELECT churn_type, mrr_cents FROM metric_churn_event"
                    " WHERE churn_type = 'revenue'"
                )
            )
        ).fetchone()
        assert rev is not None
        assert rev[1] == 3000

    @pytest.mark.asyncio
    async def test_no_logo_when_other_subs_active(self, metric, db):
        """Two subs, one churns → no logo churn (still one active)."""
        await metric.handle_event(make_evt("subscription.activated", {"external_id": "sub_1"}))
        await metric.handle_event(
            make_evt("subscription.activated", {"external_id": "sub_2"}, external_id="sub_2")
        )
        await db.commit()

        await metric.handle_event(
            make_evt(
                "subscription.churned",
                {"external_id": "sub_1", "prev_mrr_cents": 5000},
                occurred_at=T1,
            )
        )
        await db.commit()

        logo = (
            await db.execute(
                text("SELECT COUNT(*) FROM metric_churn_event WHERE churn_type = 'logo'")
            )
        ).scalar()
        assert logo == 0

        state = (
            await db.execute(
                text(
                    "SELECT active_subscriptions, churned_at"
                    " FROM metric_churn_customer_state"
                    " WHERE customer_id = 'cus_1'"
                )
            )
        ).fetchone()
        assert state[0] == 1
        assert state[1] is None

    @pytest.mark.asyncio
    async def test_canceled_event(self, metric, db):
        await metric.handle_event(
            make_evt(
                "subscription.canceled",
                {"external_id": "sub_1", "mrr_cents": 5000, "cancel_reason": "too expensive"},
            )
        )
        await db.commit()

        row = (
            await db.execute(
                text("SELECT churn_type, cancel_reason, mrr_cents FROM metric_churn_event")
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "canceled"
        assert row[1] == "too expensive"
        assert row[2] == 5000

    @pytest.mark.asyncio
    async def test_reactivation_clears_churned(self, metric, db):
        """Reactivation resets churned_at and increments active count."""
        await metric.handle_event(make_evt("subscription.activated", {"external_id": "sub_1"}))
        await metric.handle_event(
            make_evt(
                "subscription.churned",
                {"external_id": "sub_1", "prev_mrr_cents": 5000},
                occurred_at=T1,
            )
        )
        await db.commit()

        await metric.handle_event(
            make_evt("subscription.reactivated", {"external_id": "sub_1"}, occurred_at=T2)
        )
        await db.commit()

        row = (
            await db.execute(
                text(
                    "SELECT active_subscriptions, churned_at"
                    " FROM metric_churn_customer_state"
                    " WHERE customer_id = 'cus_1'"
                )
            )
        ).fetchone()
        assert row[0] == 1
        assert row[1] is None
