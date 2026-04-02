"""Integration tests for MrrMetric against real PostgreSQL."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from subscriptions.metrics.mrr.metric import MrrMetric

from .conftest import SRC_PG, T1, T2, T3, make_evt

pytestmark = pytest.mark.integration

_e = lambda *a, **kw: make_evt(*a, source_id=SRC_PG, **kw)  # noqa: E731


class TestMrrPg:
    @pytest.fixture
    def metric(self, pg_db) -> MrrMetric:
        m = MrrMetric()
        m.init(db=pg_db)
        return m

    async def test_snapshot_and_movement(self, metric, pg_db):
        await metric.handle_event(
            _e(
                "subscription.created",
                {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
            )
        )
        await pg_db.commit()

        snap = (
            await pg_db.execute(
                text(
                    "SELECT mrr_cents, mrr_base_cents"
                    " FROM metric_mrr_snapshot WHERE subscription_id = 'sub_1'"
                )
            )
        ).fetchone()
        assert snap[0] == 5000
        assert snap[1] == 5000

        move = (
            await pg_db.execute(
                text(
                    "SELECT movement_type, amount_cents"
                    " FROM metric_mrr_movement WHERE subscription_id = 'sub_1'"
                )
            )
        ).fetchone()
        assert move[0] == "new"
        assert move[1] == 5000

    async def test_expansion_contraction_churn_reactivation(self, metric, pg_db):
        """Full MRR lifecycle on real PG."""
        await metric.handle_event(
            _e(
                "subscription.created",
                {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
            )
        )
        await metric.handle_event(
            _e(
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
        await metric.handle_event(
            _e(
                "subscription.churned",
                {"external_id": "sub_1", "prev_mrr_cents": 9000, "currency": "USD"},
                occurred_at=T2,
            )
        )
        await metric.handle_event(
            _e(
                "subscription.reactivated",
                {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
                occurred_at=T3,
            )
        )
        await pg_db.commit()

        snap = (
            await pg_db.execute(
                text("SELECT mrr_cents FROM metric_mrr_snapshot WHERE subscription_id = 'sub_1'")
            )
        ).fetchone()
        assert snap[0] == 5000

        moves = (
            await pg_db.execute(
                text(
                    "SELECT movement_type, amount_cents"
                    " FROM metric_mrr_movement ORDER BY occurred_at"
                )
            )
        ).fetchall()
        assert len(moves) == 4
        assert moves[0] == ("new", 5000)
        assert moves[1] == ("expansion", 4000)
        assert moves[2] == ("churn", -9000)
        assert moves[3] == ("reactivation", 5000)

    async def test_idempotent_replay(self, metric, pg_db):
        event = _e(
            "subscription.created",
            {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
        )
        await metric.handle_event(event)
        await pg_db.commit()
        await metric.handle_event(event)
        await pg_db.commit()

        count = (await pg_db.execute(text("SELECT COUNT(*) FROM metric_mrr_movement"))).scalar()
        assert count == 1

    async def test_query_via_engine(self, pg_db):
        """Feed events then query MRR through MetricsEngine."""
        from subscriptions.engine import MetricsEngine

        m = MrrMetric()
        m.init(db=pg_db)
        await m.handle_event(
            _e(
                "subscription.created",
                {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
            )
        )
        await m.handle_event(
            _e(
                "subscription.created",
                {"external_id": "sub_2", "mrr_cents": 3000, "currency": "USD"},
                external_id="sub_2",
                customer_id="cus_2",
            )
        )
        await pg_db.commit()

        engine = MetricsEngine(db=pg_db)
        result = await engine.query("mrr", {"query_type": "current"})
        assert result == 8000
