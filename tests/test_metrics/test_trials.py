"""Tests for TrialsMetric.handle_event — SQLite in-memory."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tidemill.metrics.trials.metric import TrialsMetric

from .conftest import T0, T1, T2, make_evt


class TestTrialsHandler:
    @pytest.fixture
    def metric(self, db) -> TrialsMetric:
        m = TrialsMetric()
        m.init(db=db)
        return m

    @pytest.mark.asyncio
    async def test_trial_started(self, metric, db):
        event = make_evt(
            "subscription.trial_started",
            {"external_id": "sub_1", "trial_start": "2026-01-15", "trial_end": "2026-02-14"},
        )
        await metric.handle_event(event)
        await db.commit()

        row = (
            await db.execute(
                text(
                    "SELECT event_type, subscription_id, customer_id"
                    " FROM metric_trial_event WHERE subscription_id = 'sub_1'"
                )
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "started"
        assert row[1] == "sub_1"
        assert row[2] == "cus_1"

    @pytest.mark.asyncio
    async def test_trial_converted(self, metric, db):
        await metric.handle_event(
            make_evt(
                "subscription.trial_started",
                {"external_id": "sub_1"},
                occurred_at=T0,
            )
        )
        await metric.handle_event(
            make_evt(
                "subscription.trial_converted",
                {"external_id": "sub_1", "mrr_cents": 7900},
                occurred_at=T1,
                external_id="sub_1:converted",
            )
        )
        await db.commit()

        rows = (
            await db.execute(
                text(
                    "SELECT event_type FROM metric_trial_event"
                    " WHERE subscription_id = 'sub_1'"
                    " ORDER BY occurred_at"
                )
            )
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][0] == "started"
        assert rows[1][0] == "converted"

    @pytest.mark.asyncio
    async def test_trial_expired(self, metric, db):
        await metric.handle_event(
            make_evt(
                "subscription.trial_started",
                {"external_id": "sub_1"},
                occurred_at=T0,
            )
        )
        await metric.handle_event(
            make_evt(
                "subscription.trial_expired",
                {"external_id": "sub_1"},
                occurred_at=T1,
                external_id="sub_1:expired",
            )
        )
        await db.commit()

        rows = (
            await db.execute(
                text(
                    "SELECT event_type FROM metric_trial_event"
                    " WHERE subscription_id = 'sub_1'"
                    " ORDER BY occurred_at"
                )
            )
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][0] == "started"
        assert rows[1][0] == "expired"

    @pytest.mark.asyncio
    async def test_idempotent_replay(self, metric, db):
        """Processing the same event twice → one row."""
        event = make_evt(
            "subscription.trial_started",
            {"external_id": "sub_1"},
        )
        await metric.handle_event(event)
        await db.commit()
        await metric.handle_event(event)
        await db.commit()

        count = (await db.execute(text("SELECT COUNT(*) FROM metric_trial_event"))).scalar()
        assert count == 1

    @pytest.mark.asyncio
    async def test_multiple_trials(self, metric, db):
        """Different subscriptions create separate trial events."""
        await metric.handle_event(
            make_evt(
                "subscription.trial_started",
                {"external_id": "sub_1"},
                occurred_at=T0,
            )
        )
        await metric.handle_event(
            make_evt(
                "subscription.trial_started",
                {"external_id": "sub_2"},
                customer_id="cus_2",
                external_id="sub_2",
                occurred_at=T1,
            )
        )
        await db.commit()

        count = (await db.execute(text("SELECT COUNT(*) FROM metric_trial_event"))).scalar()
        assert count == 2

    @pytest.mark.asyncio
    async def test_full_funnel(self, metric, db):
        """Full trial funnel: 3 started, 2 converted, 1 expired."""
        for i in range(3):
            await metric.handle_event(
                make_evt(
                    "subscription.trial_started",
                    {"external_id": f"sub_{i}"},
                    customer_id=f"cus_{i}",
                    external_id=f"sub_{i}",
                    occurred_at=T0,
                )
            )

        for i in range(2):
            await metric.handle_event(
                make_evt(
                    "subscription.trial_converted",
                    {"external_id": f"sub_{i}", "mrr_cents": 7900},
                    customer_id=f"cus_{i}",
                    external_id=f"sub_{i}:converted",
                    occurred_at=T1,
                )
            )

        await metric.handle_event(
            make_evt(
                "subscription.trial_expired",
                {"external_id": "sub_2"},
                customer_id="cus_2",
                external_id="sub_2:expired",
                occurred_at=T2,
            )
        )
        await db.commit()

        rows = (
            await db.execute(
                text(
                    "SELECT event_type, COUNT(*) as cnt FROM metric_trial_event"
                    " GROUP BY event_type ORDER BY event_type"
                )
            )
        ).fetchall()
        by_type = {r[0]: r[1] for r in rows}
        assert by_type["started"] == 3
        assert by_type["converted"] == 2
        assert by_type["expired"] == 1
