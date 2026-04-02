"""Tests for the query algebra and SQL compilation.

All tests are database-free — they compile QueryFragments into SQLAlchemy
Select statements and inspect the generated SQL string.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy.dialects import postgresql

from subscriptions.metrics import QuerySpec
from subscriptions.metrics.churn import ChurnEventCube
from subscriptions.metrics.mrr import MRRMovementCube, MRRSnapshotCube
from subscriptions.metrics.query import (
    QueryFragment,
)
from subscriptions.metrics.retention import RetentionCohortCube


def _sql(stmt) -> str:
    """Compile a SQLAlchemy Select to a PostgreSQL SQL string."""
    return str(stmt.compile(dialect=postgresql.dialect()))


def _normalize(sql: str) -> str:
    """Collapse whitespace for easier assertion."""
    return re.sub(r"\s+", " ", sql).strip()


# ── Fragment algebra ─────────────────────────────────────────────────────


class TestQueryFragmentAlgebra:
    def test_identity_element(self):
        """Empty fragment is the identity: x + empty == x."""
        f = QueryFragment(source="t", measures=(None,))  # type: ignore[arg-type]
        empty = QueryFragment()
        result = f + empty
        assert result.source == "t"
        assert result.measures == f.measures

    def test_commutativity(self):
        """a + b should have the same joins as b + a."""
        a = QueryFragment(joins=frozenset({"x"}), filters=())
        b = QueryFragment(joins=frozenset({"y"}), filters=())
        assert (a + b).joins == (b + a).joins == frozenset({"x", "y"})

    def test_associativity(self):
        """(a + b) + c == a + (b + c) for joins."""
        a = QueryFragment(joins=frozenset({"x"}))
        b = QueryFragment(joins=frozenset({"y"}))
        c = QueryFragment(joins=frozenset({"z"}))
        assert ((a + b) + c).joins == (a + (b + c)).joins

    def test_source_takes_first_non_none(self):
        a = QueryFragment(source="table_a")
        b = QueryFragment(source="table_b")
        assert (a + b).source == "table_a"
        assert (QueryFragment() + b).source == "table_b"

    def test_time_grain_takes_first_non_none(self):
        from subscriptions.metrics.query import TimeGrainExpr

        tg1 = TimeGrainExpr("col1", "month")
        tg2 = TimeGrainExpr("col2", "day")
        a = QueryFragment(time_grain=tg1)
        b = QueryFragment(time_grain=tg2)
        assert (a + b).time_grain == tg1
        assert (QueryFragment() + b).time_grain == tg2

    def test_measures_accumulate(self):
        from subscriptions.metrics.query import MeasureExpr

        m1 = MeasureExpr("sum", "x", "x")
        m2 = MeasureExpr("count", "y", "y")
        a = QueryFragment(measures=(m1,))
        b = QueryFragment(measures=(m2,))
        assert (a + b).measures == (m1, m2)


# ── Cube introspection ─────────────────────────────────────────────────


class TestCubeIntrospection:
    def test_mrr_snapshot_dimensions(self):
        dims = MRRSnapshotCube.available_dimensions()
        assert "plan_interval" in dims
        assert "customer_country" in dims
        assert "currency" in dims
        assert "source_id" in dims
        assert "plan_id" in dims
        # New Stripe-sourced dimensions
        assert "plan_name" in dims
        assert "product_name" in dims
        assert "billing_scheme" in dims
        assert "usage_type" in dims
        assert "collection_method" in dims
        assert "cancel_at_period_end" in dims

    def test_mrr_snapshot_measures(self):
        measures = MRRSnapshotCube.available_measures()
        assert "mrr" in measures
        assert "mrr_original" in measures
        assert "count" in measures

    def test_mrr_snapshot_time_dimensions(self):
        assert MRRSnapshotCube.available_time_dimensions() == ["snapshot_at"]

    def test_mrr_movement_dimensions(self):
        dims = MRRMovementCube.available_dimensions()
        assert "movement_type" in dims
        assert "plan_interval" in dims

    def test_churn_event_dimensions(self):
        dims = ChurnEventCube.available_dimensions()
        assert "churn_type" in dims
        assert "customer_country" in dims
        assert "cancel_reason" in dims
        # ChurnEventCube has no subscription join
        assert "plan_id" not in dims

    def test_retention_cohort_dimensions(self):
        dims = RetentionCohortCube.available_dimensions()
        assert "cohort_month" in dims
        assert "active_month" in dims
        assert "customer_country" in dims

    def test_unknown_dimension_raises(self):
        with pytest.raises(ValueError, match="Unknown dimension 'nonexistent'"):
            MRRSnapshotCube.dimension("nonexistent")

    def test_unknown_filter_raises(self):
        with pytest.raises(ValueError, match="Cannot filter on unknown dimension"):
            MRRSnapshotCube.filter("nonexistent", "=", "x")

    def test_unknown_time_dimension_raises(self):
        with pytest.raises(ValueError, match="Unknown time dimension"):
            MRRSnapshotCube.time_grain("nonexistent", "month")


# ── MRR Snapshot — SQL compilation ───────────────────────────────────────


class TestMRRSnapshotCompilation:
    def test_plain_aggregate(self):
        """No spec — just a measure + raw WHERE."""
        m = MRRSnapshotCube
        q = m.measures.mrr + m.where("s.mrr_base_cents", ">", 0)
        stmt, params = q.compile(m)
        sql = _normalize(_sql(stmt))

        assert "sum(s.mrr_base_cents)" in sql.lower()
        assert "metric_mrr_snapshot" in sql
        assert "JOIN" not in sql
        assert params["s_mrr_base_cents_gt"] == 0

    def test_filter_without_dimension_adds_joins(self):
        """Filtering on plan_interval should add subscription + plan joins."""
        m = MRRSnapshotCube
        q = m.measures.mrr + m.filter("plan_interval", "=", "yearly")
        stmt, params = q.compile(m)
        sql = _normalize(_sql(stmt))

        assert "JOIN subscription" in sql
        assert "JOIN plan" in sql
        assert "p.interval" in sql
        assert params["plan_interval"] == "yearly"
        # No GROUP BY since we didn't add a dimension
        assert "GROUP BY" not in sql

    def test_dimension_adds_join_and_group_by(self):
        """Requesting plan_interval dimension adds joins and GROUP BY."""
        m = MRRSnapshotCube
        q = m.measures.mrr + m.dimension("plan_interval")
        stmt, params = q.compile(m)
        sql = _normalize(_sql(stmt))

        assert "JOIN subscription" in sql
        assert "JOIN plan" in sql
        assert "GROUP BY" in sql
        assert "p.interval" in sql

    def test_multiple_dimensions(self):
        """Two dimensions from different joins."""
        m = MRRSnapshotCube
        q = m.measures.mrr + m.dimension("plan_interval") + m.dimension("customer_country")
        stmt, params = q.compile(m)
        sql = _normalize(_sql(stmt))

        assert "JOIN subscription" in sql
        assert "JOIN plan" in sql
        assert "JOIN customer" in sql
        assert "p.interval" in sql
        assert "c.country" in sql

    def test_dimension_on_source_table_no_join(self):
        """currency dimension lives on the source table — no join needed."""
        m = MRRSnapshotCube
        q = m.measures.mrr + m.dimension("currency")
        stmt, params = q.compile(m)
        sql = _normalize(_sql(stmt))

        assert "s.currency" in sql
        assert "GROUP BY" in sql
        assert "JOIN" not in sql

    def test_filter_plus_dimension(self):
        """Filter on customer_country + dimension on plan_id."""
        m = MRRSnapshotCube
        q = (
            m.measures.mrr
            + m.filter("customer_country", "in", ["US", "DE"])
            + m.dimension("plan_id")
        )
        stmt, params = q.compile(m)
        sql = _normalize(_sql(stmt))

        assert "JOIN subscription" in sql
        assert "JOIN customer" in sql
        assert "c.country" in sql  # filter
        assert "sub.plan_id" in sql  # dimension
        assert "GROUP BY" in sql
        assert params["customer_country"] == ["US", "DE"]

    def test_time_grain(self):
        """Adding time grain produces DATE_TRUNC in SELECT and GROUP BY."""
        m = MRRSnapshotCube
        q = m.measures.mrr + m.time_grain("snapshot_at", "month")
        stmt, params = q.compile(m)
        sql = _normalize(_sql(stmt))

        assert "date_trunc" in sql.lower()
        assert "'month'" in sql
        assert "s.snapshot_at" in sql
        assert "GROUP BY" in sql

    def test_time_grain_plus_dimension(self):
        m = MRRSnapshotCube
        q = m.measures.mrr + m.time_grain("snapshot_at", "month") + m.dimension("plan_interval")
        stmt, params = q.compile(m)
        sql = _normalize(_sql(stmt))

        assert "date_trunc" in sql.lower()
        assert "p.interval" in sql
        assert "JOIN plan" in sql

    def test_count_distinct_measure(self):
        m = MRRSnapshotCube
        q = m.measures.count
        stmt, params = q.compile(m)
        sql = _normalize(_sql(stmt))

        # SQLAlchemy renders count(distinct(col)) with extra parens
        assert "count(distinct" in sql.lower()
        assert "s.subscription_id" in sql.lower()

    def test_chained_join_dependency(self):
        """plan depends on subscription — both should be joined."""
        m = MRRSnapshotCube
        q = m.measures.mrr + m.dimension("plan_interval")
        stmt, params = q.compile(m)
        sql = _sql(stmt)

        # subscription must appear before plan in the SQL
        sub_pos = sql.index("JOIN subscription")
        plan_pos = sql.index("JOIN plan")
        assert sub_pos < plan_pos

    def test_product_join_chain(self):
        """product depends on plan depends on subscription — all three joined in order."""
        m = MRRSnapshotCube
        q = m.measures.mrr + m.dimension("product_name")
        stmt, params = q.compile(m)
        sql = _sql(stmt)

        assert "JOIN subscription" in sql
        assert "JOIN plan" in sql
        assert "JOIN product" in sql
        # Correct dependency order
        sub_pos = sql.index("JOIN subscription")
        plan_pos = sql.index("JOIN plan")
        prod_pos = sql.index("JOIN product")
        assert sub_pos < plan_pos < prod_pos
        assert "prod.name" in sql

    def test_plan_name_dimension(self):
        m = MRRSnapshotCube
        q = m.measures.mrr + m.dimension("plan_name")
        stmt, params = q.compile(m)
        sql = _normalize(_sql(stmt))

        assert "p.name" in sql
        assert "JOIN plan" in sql
        assert "GROUP BY" in sql

    def test_billing_scheme_dimension(self):
        m = MRRSnapshotCube
        q = m.measures.mrr + m.dimension("billing_scheme")
        stmt, params = q.compile(m)
        sql = _normalize(_sql(stmt))

        assert "p.billing_scheme" in sql
        assert "JOIN plan" in sql

    def test_collection_method_dimension(self):
        m = MRRSnapshotCube
        q = m.measures.mrr + m.dimension("collection_method")
        stmt, params = q.compile(m)
        sql = _normalize(_sql(stmt))

        assert "sub.collection_method" in sql
        assert "JOIN subscription" in sql
        # collection_method is on subscription, no plan join needed
        assert "JOIN plan" not in sql

    def test_cancel_at_period_end_dimension(self):
        m = MRRSnapshotCube
        q = m.measures.mrr + m.dimension("cancel_at_period_end")
        stmt, params = q.compile(m)
        sql = _normalize(_sql(stmt))

        assert "sub.cancel_at_period_end" in sql

    def test_between_filter(self):
        m = MRRSnapshotCube
        q = m.measures.mrr + m.filter("snapshot_at", "between", ("2025-01-01", "2025-12-31"))
        stmt, params = q.compile(m)
        sql = _normalize(_sql(stmt))

        assert "BETWEEN" in sql
        assert params["snapshot_at_start"] == "2025-01-01"
        assert params["snapshot_at_end"] == "2025-12-31"

    def test_lte_filter(self):
        m = MRRSnapshotCube
        q = m.measures.mrr + m.filter("snapshot_at", "<=", "2025-06-01")
        stmt, params = q.compile(m)
        sql = _normalize(_sql(stmt))

        assert "<=" in sql
        assert params["snapshot_at"] == "2025-06-01"


# ── MRR Movement — SQL compilation ──────────────────────────────────────


class TestMRRMovementCompilation:
    def test_breakdown_query(self):
        """MRR breakdown: sum amount grouped by movement_type."""
        mm = MRRMovementCube
        q = (
            mm.measures.amount
            + mm.dimension("movement_type")
            + mm.filter("occurred_at", "between", ("2025-01-01", "2025-03-01"))
        )
        stmt, params = q.compile(mm)
        sql = _normalize(_sql(stmt))

        assert "sum(m.amount_base_cents)" in sql.lower()
        assert "m.movement_type" in sql
        assert "GROUP BY" in sql
        assert "BETWEEN" in sql
        # No joins needed — movement_type is on the source table
        assert "JOIN" not in sql

    def test_breakdown_with_plan_dimension(self):
        """Adding plan_id dimension to breakdown adds subscription join."""
        mm = MRRMovementCube
        q = (
            mm.measures.amount
            + mm.dimension("movement_type")
            + mm.dimension("plan_id")
            + mm.filter("occurred_at", "between", ("2025-01-01", "2025-03-01"))
        )
        stmt, params = q.compile(mm)
        sql = _normalize(_sql(stmt))

        assert "JOIN subscription" in sql
        assert "sub.plan_id" in sql
        assert "m.movement_type" in sql

    def test_time_series(self):
        mm = MRRMovementCube
        q = (
            mm.measures.amount
            + mm.time_grain("occurred_at", "month")
            + mm.filter("occurred_at", "between", ("2025-01-01", "2025-12-31"))
        )
        stmt, params = q.compile(mm)
        sql = _normalize(_sql(stmt))

        assert "date_trunc" in sql.lower()
        assert "'month'" in sql
        assert "m.occurred_at" in sql


# ── Churn Event — SQL compilation ────────────────────────────────────────


class TestChurnEventCompilation:
    def test_basic_churn_count(self):
        """Count churn events filtered by type and date range."""
        ce = ChurnEventCube
        q = (
            ce.measures.count
            + ce.filter("churn_type", "=", "logo")
            + ce.filter("occurred_at", "between", ("2025-01-01", "2025-03-01"))
        )
        stmt, params = q.compile(ce)
        sql = _normalize(_sql(stmt))

        assert "count(*)" in sql.lower()
        assert "ce.churn_type" in sql
        assert "JOIN" not in sql  # no joins needed
        assert params["churn_type"] == "logo"

    def test_churn_with_country_dimension(self):
        ce = ChurnEventCube
        q = (
            ce.measures.count
            + ce.dimension("customer_country")
            + ce.filter("occurred_at", "between", ("2025-01-01", "2025-03-01"))
        )
        stmt, params = q.compile(ce)
        sql = _normalize(_sql(stmt))

        assert "JOIN customer" in sql
        assert "c.country" in sql
        assert "GROUP BY" in sql

    def test_churn_cancel_reason_dimension(self):
        """cancel_reason is on the churn event table — no join needed."""
        ce = ChurnEventCube
        q = ce.measures.count + ce.dimension("cancel_reason")
        stmt, params = q.compile(ce)
        sql = _normalize(_sql(stmt))

        assert "ce.cancel_reason" in sql
        assert "GROUP BY" in sql
        assert "JOIN" not in sql


# ── Retention — SQL compilation ──────────────────────────────────────────


class TestRetentionCompilation:
    def test_cohort_matrix(self):
        """Cohort matrix: cohort_size + active_count grouped by cohort_month + active_month."""
        rc = RetentionCohortCube
        q = (
            rc.measures.cohort_size
            + rc.measures.active_count
            + rc.dimension("cohort_month")
            + rc.dimension("active_month")
            + rc.filter("cohort_month_time", "between", ("2025-01-01", "2025-06-01"))
        )
        stmt, params = q.compile(rc)
        sql = _normalize(_sql(stmt))

        assert "rc.customer_id" in sql.lower()
        assert "ra.customer_id" in sql.lower()
        assert sql.lower().count("count(distinct") == 2
        assert "rc.cohort_month" in sql
        assert "ra.active_month" in sql
        assert "JOIN metric_retention_activity" in sql
        assert "BETWEEN" in sql

    def test_cohort_with_country(self):
        rc = RetentionCohortCube
        q = (
            rc.measures.cohort_size
            + rc.dimension("cohort_month")
            + rc.dimension("customer_country")
        )
        stmt, params = q.compile(rc)
        sql = _normalize(_sql(stmt))

        assert "JOIN customer" in sql
        assert "c.country" in sql
        assert "rc.cohort_month" in sql


# ── QuerySpec integration ────────────────────────────────────────────────


class TestQuerySpec:
    def test_apply_spec_dimensions(self):
        """apply_spec translates dimension names into fragments."""
        spec = QuerySpec(dimensions=["plan_interval", "customer_country"])
        m = MRRSnapshotCube

        q = m.measures.mrr + m.apply_spec(spec)
        stmt, params = q.compile(m)
        sql = _normalize(_sql(stmt))

        assert "p.interval" in sql
        assert "c.country" in sql
        assert "JOIN subscription" in sql
        assert "JOIN plan" in sql
        assert "JOIN customer" in sql

    def test_apply_spec_filters_equality(self):
        spec = QuerySpec(filters={"customer_country": "US"})
        m = MRRSnapshotCube

        q = m.measures.mrr + m.apply_spec(spec)
        stmt, params = q.compile(m)
        sql = _normalize(_sql(stmt))

        assert "c.country" in sql
        assert "JOIN customer" in sql
        assert params["customer_country"] == "US"

    def test_apply_spec_filters_in_operator(self):
        spec = QuerySpec(filters={"plan_interval": {"in": ["monthly", "yearly"]}})
        m = MRRSnapshotCube

        q = m.measures.mrr + m.apply_spec(spec)
        stmt, params = q.compile(m)
        sql = _normalize(_sql(stmt))

        assert "p.interval" in sql
        assert "IN" in sql
        assert params["plan_interval"] == ["monthly", "yearly"]

    def test_apply_spec_granularity(self):
        spec = QuerySpec(granularity="quarter")
        m = MRRSnapshotCube

        q = m.measures.mrr + m.apply_spec(spec)
        stmt, params = q.compile(m)
        sql = _normalize(_sql(stmt))

        assert "date_trunc" in sql.lower()
        assert "'quarter'" in sql

    def test_apply_spec_combined(self):
        """Full spec: dimensions + filters + granularity."""
        spec = QuerySpec(
            dimensions=["plan_interval"],
            filters={"customer_country": "DE"},
            granularity="month",
        )
        m = MRRSnapshotCube

        q = m.measures.mrr + m.where("s.mrr_base_cents", ">", 0) + m.apply_spec(spec)
        stmt, params = q.compile(m)
        sql = _normalize(_sql(stmt))

        assert "date_trunc" in sql.lower()
        assert "p.interval" in sql
        assert "c.country" in sql
        assert "s.mrr_base_cents" in sql
        assert "JOIN plan" in sql
        assert "JOIN customer" in sql
        assert params["customer_country"] == "DE"
        assert params["s_mrr_base_cents_gt"] == 0

    def test_apply_spec_validates_dimensions(self):
        spec = QuerySpec(dimensions=["nonexistent"])
        with pytest.raises(ValueError, match="Unknown dimension 'nonexistent'"):
            MRRSnapshotCube.apply_spec(spec)

    def test_apply_spec_validates_filters(self):
        spec = QuerySpec(filters={"bogus": "x"})
        with pytest.raises(ValueError, match="Cannot filter on unknown dimension"):
            MRRSnapshotCube.apply_spec(spec)

    def test_empty_spec_is_noop(self):
        spec = QuerySpec()
        m = MRRSnapshotCube
        q = m.measures.mrr + m.apply_spec(spec)
        stmt, params = q.compile(m)
        sql = _normalize(_sql(stmt))

        assert "JOIN" not in sql
        assert "GROUP BY" not in sql


# ── to_sql convenience ───────────────────────────────────────────────────


class TestToSql:
    def test_to_sql_returns_string(self):
        m = MRRSnapshotCube
        q = m.measures.mrr + m.where("s.mrr_base_cents", ">", 0)
        sql = q.to_sql(m)

        assert isinstance(sql, str)
        assert "metric_mrr_snapshot" in sql
        assert "sum" in sql.lower()

    def test_to_sql_substitutes_simple_params(self):
        m = MRRSnapshotCube
        q = m.measures.mrr + m.filter("plan_interval", "=", "monthly")
        sql = q.to_sql(m)

        assert "'monthly'" in sql


# ── Join deduplication ───────────────────────────────────────────────────


class TestJoinDeduplication:
    def test_same_join_not_duplicated(self):
        """Filtering and dimensioning on same join should produce one JOIN."""
        m = MRRSnapshotCube
        q = (
            m.measures.mrr
            + m.filter("plan_interval", "=", "monthly")
            + m.dimension("plan_interval")
        )
        stmt, params = q.compile(m)
        sql = _sql(stmt)

        # Each join should appear exactly once
        assert sql.count("JOIN subscription") == 1
        assert sql.count("JOIN plan") == 1

    def test_customer_join_shared(self):
        """Filter + dimension both needing customer join."""
        m = MRRSnapshotCube
        q = (
            m.measures.mrr
            + m.filter("customer_country", "=", "US")
            + m.dimension("customer_country")
        )
        stmt, params = q.compile(m)
        sql = _sql(stmt)

        assert sql.count("JOIN customer") == 1


# ── Edge cases ───────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_compile_without_model_no_joins(self):
        """Fragments with no joins can compile without a model."""
        m = MRRSnapshotCube
        q = m.measures.mrr  # no joins needed
        stmt, params = q.compile()  # model=None is OK
        sql = _normalize(_sql(stmt))
        assert "sum(s.mrr_base_cents)" in sql.lower()

    def test_compile_without_model_with_joins_raises(self):
        m = MRRSnapshotCube
        q = m.measures.mrr + m.dimension("plan_interval")
        with pytest.raises(ValueError, match="no Cube was provided"):
            q.compile()  # needs model for join resolution

    def test_measure_accessor_unknown_raises(self):
        with pytest.raises(AttributeError, match="No measure 'bogus'"):
            _ = MRRSnapshotCube.measures.bogus

    def test_multiple_measures(self):
        m = MRRSnapshotCube
        q = m.measures.mrr + m.measures.count
        stmt, params = q.compile(m)
        sql = _normalize(_sql(stmt))

        assert "sum(s.mrr_base_cents)" in sql.lower()
        assert "count(distinct" in sql.lower()
        assert "s.subscription_id" in sql.lower()
