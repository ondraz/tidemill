"""Tests for MrrMetric.handle_event — SQLite in-memory."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from subscriptions.metrics.mrr.metric import MrrMetric

from .conftest import T1, T2, make_evt


class TestMrrHandler:
    @pytest.fixture
    def metric(self, db) -> MrrMetric:
        m = MrrMetric()
        m.init(db=db)
        return m

    @pytest.mark.asyncio
    async def test_snapshot_upsert_on_created(self, metric, db):
        """subscription.created → snapshot with correct mrr_cents."""
        event = make_evt(
            "subscription.created",
            {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
        )
        await metric.handle_event(event)
        await db.commit()

        row = (
            await db.execute(
                text(
                    "SELECT mrr_cents, mrr_base_cents, subscription_id"
                    " FROM metric_mrr_snapshot WHERE subscription_id = 'sub_1'"
                )
            )
        ).fetchone()
        assert row is not None
        assert row[0] == 5000
        assert row[1] == 5000  # USD → USD passthrough
        assert row[2] == "sub_1"

    @pytest.mark.asyncio
    async def test_created_no_movement(self, metric, db):
        """subscription.created only upserts snapshot, no movement."""
        event = make_evt(
            "subscription.created",
            {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
        )
        await metric.handle_event(event)
        await db.commit()

        row = (
            await db.execute(
                text(
                    "SELECT movement_type FROM metric_mrr_movement WHERE subscription_id = 'sub_1'"
                )
            )
        ).fetchone()
        assert row is None  # no movement on created

    @pytest.mark.asyncio
    async def test_movement_appended_on_activated(self, metric, db):
        event = make_evt(
            "subscription.activated",
            {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
        )
        await metric.handle_event(event)
        await db.commit()

        row = (
            await db.execute(
                text(
                    "SELECT movement_type, amount_cents FROM metric_mrr_movement"
                    " WHERE subscription_id = 'sub_1'"
                )
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "new"
        assert row[1] == 5000

    @pytest.mark.asyncio
    async def test_expansion(self, metric, db):
        """subscription.changed with higher MRR → expansion movement."""
        await metric.handle_event(
            make_evt(
                "subscription.activated",
                {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
            )
        )
        await db.commit()

        await metric.handle_event(
            make_evt(
                "subscription.changed",
                {
                    "external_id": "sub_1",
                    "prev_mrr_cents": 5000,
                    "new_mrr_cents": 9000,
                    "currency": "USD",
                },
                occurred_at=T1,
            )
        )
        await db.commit()

        snap = (
            await db.execute(
                text("SELECT mrr_cents FROM metric_mrr_snapshot WHERE subscription_id = 'sub_1'")
            )
        ).fetchone()
        assert snap[0] == 9000

        moves = (
            await db.execute(
                text(
                    "SELECT movement_type, amount_cents FROM metric_mrr_movement"
                    " ORDER BY occurred_at"
                )
            )
        ).fetchall()
        assert len(moves) == 2
        assert moves[1][0] == "expansion"
        assert moves[1][1] == 4000

    @pytest.mark.asyncio
    async def test_contraction(self, metric, db):
        await metric.handle_event(
            make_evt(
                "subscription.activated",
                {"external_id": "sub_1", "mrr_cents": 9000, "currency": "USD"},
            )
        )
        await db.commit()

        await metric.handle_event(
            make_evt(
                "subscription.changed",
                {
                    "external_id": "sub_1",
                    "prev_mrr_cents": 9000,
                    "new_mrr_cents": 5000,
                    "currency": "USD",
                },
                occurred_at=T1,
            )
        )
        await db.commit()

        moves = (
            await db.execute(
                text(
                    "SELECT movement_type, amount_cents FROM metric_mrr_movement"
                    " ORDER BY occurred_at"
                )
            )
        ).fetchall()
        assert moves[1][0] == "contraction"
        assert moves[1][1] == -4000

    @pytest.mark.asyncio
    async def test_churn_movement(self, metric, db):
        """subscription.churned → snapshot 0, negative churn movement."""
        await metric.handle_event(
            make_evt(
                "subscription.created",
                {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
            )
        )
        await db.commit()

        await metric.handle_event(
            make_evt(
                "subscription.churned",
                {"external_id": "sub_1", "prev_mrr_cents": 5000, "currency": "USD"},
                occurred_at=T1,
            )
        )
        await db.commit()

        snap = (
            await db.execute(
                text("SELECT mrr_cents FROM metric_mrr_snapshot WHERE subscription_id = 'sub_1'")
            )
        ).fetchone()
        assert snap[0] == 0

        churn_move = (
            await db.execute(
                text(
                    "SELECT movement_type, amount_cents FROM metric_mrr_movement"
                    " WHERE movement_type = 'churn'"
                )
            )
        ).fetchone()
        assert churn_move is not None
        assert churn_move[1] == -5000

    @pytest.mark.asyncio
    async def test_reactivation(self, metric, db):
        await metric.handle_event(
            make_evt(
                "subscription.created",
                {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
            )
        )
        await metric.handle_event(
            make_evt(
                "subscription.churned",
                {"external_id": "sub_1", "prev_mrr_cents": 5000, "currency": "USD"},
                occurred_at=T1,
            )
        )
        await db.commit()

        await metric.handle_event(
            make_evt(
                "subscription.reactivated",
                {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
                occurred_at=T2,
            )
        )
        await db.commit()

        snap = (
            await db.execute(
                text("SELECT mrr_cents FROM metric_mrr_snapshot WHERE subscription_id = 'sub_1'")
            )
        ).fetchone()
        assert snap[0] == 5000

        react = (
            await db.execute(
                text(
                    "SELECT movement_type, amount_cents FROM metric_mrr_movement"
                    " WHERE movement_type = 'reactivation'"
                )
            )
        ).fetchone()
        assert react is not None
        assert react[1] == 5000

    @pytest.mark.asyncio
    async def test_idempotent_replay(self, metric, db):
        """Processing the same event twice → one movement row."""
        event = make_evt(
            "subscription.activated",
            {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
        )
        await metric.handle_event(event)
        await db.commit()
        await metric.handle_event(event)
        await db.commit()

        count = (await db.execute(text("SELECT COUNT(*) FROM metric_mrr_movement"))).scalar()
        assert count == 1

    @pytest.mark.asyncio
    async def test_pause_acts_as_churn(self, metric, db):
        await metric.handle_event(
            make_evt(
                "subscription.created",
                {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
            )
        )
        await db.commit()

        await metric.handle_event(
            make_evt(
                "subscription.paused",
                {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
                occurred_at=T1,
            )
        )
        await db.commit()

        snap = (
            await db.execute(
                text("SELECT mrr_cents FROM metric_mrr_snapshot WHERE subscription_id = 'sub_1'")
            )
        ).fetchone()
        assert snap[0] == 0

    @pytest.mark.asyncio
    async def test_resume_acts_as_reactivation(self, metric, db):
        await metric.handle_event(
            make_evt(
                "subscription.created",
                {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
            )
        )
        await metric.handle_event(
            make_evt(
                "subscription.paused",
                {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
                occurred_at=T1,
            )
        )
        await db.commit()

        await metric.handle_event(
            make_evt(
                "subscription.resumed",
                {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
                occurred_at=T2,
            )
        )
        await db.commit()

        snap = (
            await db.execute(
                text("SELECT mrr_cents FROM metric_mrr_snapshot WHERE subscription_id = 'sub_1'")
            )
        ).fetchone()
        assert snap[0] == 5000
