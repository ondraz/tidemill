"""SQLAlchemy Core table definitions.

Core tables represent billing entities synced from connectors (Stripe, Lago,
Kill Bill).  Metric tables are owned by individual metrics and prefixed with
``metric_``.  All monetary values use the dual-column convention:
``*_cents`` (original currency) + ``*_usd_cents`` (USD at daily FX rate).
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()

# ── Core tables (billing entities) ───────────────────────────────────────

connector_source = Table(
    "connector_source",
    metadata,
    Column("id", Text, primary_key=True),
    Column("type", Text, nullable=False),
    Column("name", Text),
    Column("config", Text),
    Column("last_synced_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

customer = Table(
    "customer",
    metadata,
    Column("id", Text, primary_key=True),
    Column("source_id", Text, ForeignKey("connector_source.id"), nullable=False),
    Column("external_id", Text, nullable=False),
    Column("name", Text),
    Column("email", Text),
    Column("country", Text),
    Column("currency", Text),
    Column("metadata_", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True)),
    UniqueConstraint("source_id", "external_id", name="uq_customer_source"),
)

plan = Table(
    "plan",
    metadata,
    Column("id", Text, primary_key=True),
    Column("source_id", Text, ForeignKey("connector_source.id"), nullable=False),
    Column("external_id", Text, nullable=False),
    Column("name", Text),
    Column("interval", Text, nullable=False),
    Column("amount_cents", BigInteger),
    Column("currency", Text),
    Column("trial_period_days", Integer),
    Column("metadata_", Text),
    Column("active", Boolean, default=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("source_id", "external_id", name="uq_plan_source"),
)

subscription = Table(
    "subscription",
    metadata,
    Column("id", Text, primary_key=True),
    Column("source_id", Text, ForeignKey("connector_source.id"), nullable=False),
    Column("external_id", Text, nullable=False),
    Column("customer_id", Text, ForeignKey("customer.id"), nullable=False),
    Column("plan_id", Text, ForeignKey("plan.id"), nullable=False),
    Column("status", Text, nullable=False),
    Column("mrr_cents", BigInteger, nullable=False, default=0),
    Column("mrr_usd_cents", BigInteger, nullable=False, default=0),
    Column("currency", Text),
    Column("quantity", Integer, default=1),
    Column("started_at", DateTime(timezone=True)),
    Column("trial_start", DateTime(timezone=True)),
    Column("trial_end", DateTime(timezone=True)),
    Column("canceled_at", DateTime(timezone=True)),
    Column("ended_at", DateTime(timezone=True)),
    Column("current_period_start", DateTime(timezone=True)),
    Column("current_period_end", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True)),
    UniqueConstraint("source_id", "external_id", name="uq_subscription_source"),
)

# ── Metric tables ────────────────────────────────────────────────────────

metric_mrr_snapshot = Table(
    "metric_mrr_snapshot",
    metadata,
    Column("id", Text, primary_key=True),
    Column("source_id", Text, nullable=False),
    Column("customer_id", Text, nullable=False),
    Column("subscription_id", Text, nullable=False),
    Column("mrr_cents", BigInteger, nullable=False),
    Column("mrr_usd_cents", BigInteger, nullable=False),
    Column("currency", Text, nullable=False),
    Column("snapshot_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("source_id", "subscription_id", name="uq_mrr_snapshot_sub"),
)

metric_mrr_movement = Table(
    "metric_mrr_movement",
    metadata,
    Column("id", Text, primary_key=True),
    Column("event_id", Text, nullable=False, unique=True),
    Column("source_id", Text, nullable=False),
    Column("customer_id", Text, nullable=False),
    Column("subscription_id", Text, nullable=False),
    Column("movement_type", Text, nullable=False),
    Column("amount_cents", BigInteger, nullable=False),
    Column("amount_usd_cents", BigInteger, nullable=False),
    Column("currency", Text, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
)

metric_churn_customer_state = Table(
    "metric_churn_customer_state",
    metadata,
    Column("id", Text, primary_key=True),
    Column("source_id", Text, nullable=False),
    Column("customer_id", Text, nullable=False),
    Column("active_subscriptions", Integer, nullable=False, default=0),
    Column("first_active_at", DateTime(timezone=True)),
    Column("churned_at", DateTime(timezone=True)),
    UniqueConstraint("source_id", "customer_id", name="uq_churn_state_customer"),
)

metric_churn_event = Table(
    "metric_churn_event",
    metadata,
    Column("id", Text, primary_key=True),
    Column("event_id", Text, nullable=False, unique=True),
    Column("source_id", Text, nullable=False),
    Column("customer_id", Text, nullable=False),
    Column("churn_type", Text, nullable=False),
    Column("mrr_cents", BigInteger),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
)

metric_retention_cohort = Table(
    "metric_retention_cohort",
    metadata,
    Column("id", Text, primary_key=True),
    Column("source_id", Text, nullable=False),
    Column("customer_id", Text, nullable=False),
    Column("cohort_month", Date, nullable=False),
    UniqueConstraint("source_id", "customer_id", name="uq_retention_cohort_customer"),
)

metric_retention_activity = Table(
    "metric_retention_activity",
    metadata,
    Column("id", Text, primary_key=True),
    Column("source_id", Text, nullable=False),
    Column("customer_id", Text, nullable=False),
    Column("active_month", Date, nullable=False),
    UniqueConstraint(
        "source_id",
        "customer_id",
        "active_month",
        name="uq_retention_activity",
    ),
)
