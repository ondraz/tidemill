"""Tests for MRR waterfall query."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from tidemill.metrics.mrr.metric import MrrMetric

from .conftest import SRC_PG, make_evt

_e = lambda *a, **kw: make_evt(*a, source_id=SRC_PG, **kw)  # noqa: E731


class TestMrrWaterfallEdgeCases:
    """Edge cases that don't need PostgreSQL (no date_trunc involved)."""

    @pytest.fixture
    def metric(self, db) -> MrrMetric:
        m = MrrMetric()
        m.init(db=db)
        return m

    async def test_empty_range_returns_empty(self, metric):
        """Range with fewer than two month boundaries returns empty list."""
        result = await metric.query(
            {"query_type": "waterfall", "start": "2026-01-15", "end": "2026-01-20"}
        )
        assert result == []

    async def test_single_month_boundary_returns_empty(self, metric):
        """A range with only one month-start returns empty (need at least two)."""
        result = await metric.query(
            {"query_type": "waterfall", "start": "2026-01-01", "end": "2026-01-31"}
        )
        assert result == []


@pytest.mark.integration
class TestMrrWaterfall:
    @pytest.fixture
    def metric(self, pg_db) -> MrrMetric:
        m = MrrMetric()
        m.init(db=pg_db)
        return m

    async def test_basic_waterfall(self, metric, pg_db):
        """Events across two months produce correct waterfall rows."""
        jan = datetime(2026, 1, 10, tzinfo=UTC)
        feb = datetime(2026, 2, 10, tzinfo=UTC)

        await metric.handle_event(
            _e(
                "subscription.activated",
                {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
                occurred_at=jan,
            )
        )
        await metric.handle_event(
            _e(
                "subscription.activated",
                {"external_id": "sub_2", "mrr_cents": 3000, "currency": "USD"},
                external_id="sub_2",
                customer_id="cus_2",
                occurred_at=feb,
            )
        )
        await pg_db.commit()

        result = await metric.query(
            {"query_type": "waterfall", "start": date(2026, 1, 1), "end": date(2026, 2, 28)}
        )

        assert len(result) == 2
        # January: 0 starting → new 5000 cents
        assert result[0]["period"] == "2026-01-01"
        assert result[0]["starting_mrr"] == 0
        assert result[0]["new"] == 5000.0
        assert result[0]["ending_mrr"] == 5000.0

        # February: 5000 starting → new 3000 cents
        assert result[1]["period"] == "2026-02-01"
        assert result[1]["starting_mrr"] == 5000.0
        assert result[1]["new"] == 3000.0
        assert result[1]["ending_mrr"] == 8000.0

    async def test_waterfall_with_churn_and_expansion(self, metric, pg_db):
        """Multiple movement types within a single month."""
        jan = datetime(2026, 1, 5, tzinfo=UTC)
        jan_mid = datetime(2026, 1, 15, tzinfo=UTC)
        jan_late = datetime(2026, 1, 25, tzinfo=UTC)

        # New sub at 5000 cents
        await metric.handle_event(
            _e(
                "subscription.activated",
                {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
                occurred_at=jan,
            )
        )
        # Expand to 9000 cents
        await metric.handle_event(
            _e(
                "subscription.changed",
                {
                    "external_id": "sub_1",
                    "prev_mrr_cents": 5000,
                    "new_mrr_cents": 9000,
                    "currency": "USD",
                },
                occurred_at=jan_mid,
            )
        )
        # Another sub created then churned
        await metric.handle_event(
            _e(
                "subscription.activated",
                {"external_id": "sub_2", "mrr_cents": 2000, "currency": "USD"},
                external_id="sub_2",
                customer_id="cus_2",
                occurred_at=jan_mid,
            )
        )
        await metric.handle_event(
            _e(
                "subscription.churned",
                {"external_id": "sub_2", "prev_mrr_cents": 2000, "currency": "USD"},
                external_id="sub_2",
                customer_id="cus_2",
                occurred_at=jan_late,
            )
        )
        await pg_db.commit()

        result = await metric.query(
            {"query_type": "waterfall", "start": date(2026, 1, 1), "end": date(2026, 2, 28)}
        )

        assert len(result) == 2
        row = result[0]
        assert row["period"] == "2026-01-01"
        assert row["new"] == 7000.0  # 5000 + 2000
        assert row["expansion"] == 4000.0
        assert row["churn"] == -2000.0
        assert row["ending_mrr"] == 9000.0  # 7000 + 4000 - 2000
        # Feb: quiet month, MRR carries forward
        assert result[1]["starting_mrr"] == 9000.0
        assert result[1]["net_change"] == 0

    async def test_waterfall_accumulates_across_months(self, metric, pg_db):
        """ending_mrr carries forward as starting_mrr for quiet months."""
        jan = datetime(2026, 1, 10, tzinfo=UTC)

        await metric.handle_event(
            _e(
                "subscription.activated",
                {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
                occurred_at=jan,
            )
        )
        await pg_db.commit()

        result = await metric.query(
            {"query_type": "waterfall", "start": date(2026, 1, 1), "end": date(2026, 3, 31)}
        )

        assert len(result) == 3
        # Jan: new sub
        assert result[0]["ending_mrr"] == 5000.0
        # Feb: no movements, MRR carries forward
        assert result[1]["starting_mrr"] == 5000.0
        assert result[1]["net_change"] == 0
        assert result[1]["ending_mrr"] == 5000.0
        # Mar: same
        assert result[2]["starting_mrr"] == 5000.0
        assert result[2]["ending_mrr"] == 5000.0

    async def test_waterfall_with_baseline(self, metric, pg_db):
        """Pre-existing MRR before the waterfall range appears as starting_mrr."""
        dec = datetime(2025, 12, 10, tzinfo=UTC)

        await metric.handle_event(
            _e(
                "subscription.activated",
                {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
                occurred_at=dec,
            )
        )
        await pg_db.commit()

        result = await metric.query(
            {"query_type": "waterfall", "start": date(2026, 1, 1), "end": date(2026, 2, 28)}
        )

        assert len(result) == 2
        # Pre-existing 5000 cents shows as starting_mrr
        assert result[0]["starting_mrr"] == 5000.0
        assert result[0]["new"] == 0
        assert result[0]["ending_mrr"] == 5000.0

    async def test_waterfall_reactivation(self, metric, pg_db):
        """Reactivation movement appears in waterfall."""
        jan = datetime(2026, 1, 10, tzinfo=UTC)
        feb = datetime(2026, 2, 10, tzinfo=UTC)
        mar = datetime(2026, 3, 10, tzinfo=UTC)

        await metric.handle_event(
            _e(
                "subscription.activated",
                {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
                occurred_at=jan,
            )
        )
        await metric.handle_event(
            _e(
                "subscription.churned",
                {"external_id": "sub_1", "prev_mrr_cents": 5000, "currency": "USD"},
                occurred_at=feb,
            )
        )
        await metric.handle_event(
            _e(
                "subscription.reactivated",
                {"external_id": "sub_1", "mrr_cents": 5000, "currency": "USD"},
                occurred_at=mar,
            )
        )
        await pg_db.commit()

        result = await metric.query(
            {"query_type": "waterfall", "start": date(2026, 1, 1), "end": date(2026, 3, 31)}
        )

        assert len(result) == 3
        assert result[0]["new"] == 5000.0
        assert result[0]["ending_mrr"] == 5000.0

        assert result[1]["churn"] == -5000.0
        assert result[1]["ending_mrr"] == 0

        assert result[2]["reactivation"] == 5000.0
        assert result[2]["ending_mrr"] == 5000.0

    async def test_waterfall_contraction(self, metric, pg_db):
        """Downgrade shows as contraction in the waterfall."""
        jan = datetime(2026, 1, 10, tzinfo=UTC)
        feb = datetime(2026, 2, 10, tzinfo=UTC)

        await metric.handle_event(
            _e(
                "subscription.activated",
                {"external_id": "sub_1", "mrr_cents": 9000, "currency": "USD"},
                occurred_at=jan,
            )
        )
        await metric.handle_event(
            _e(
                "subscription.changed",
                {
                    "external_id": "sub_1",
                    "prev_mrr_cents": 9000,
                    "new_mrr_cents": 5000,
                    "currency": "USD",
                },
                occurred_at=feb,
            )
        )
        await pg_db.commit()

        result = await metric.query(
            {"query_type": "waterfall", "start": date(2026, 1, 1), "end": date(2026, 2, 28)}
        )

        assert result[1]["contraction"] == -4000.0
        assert result[1]["ending_mrr"] == 5000.0
