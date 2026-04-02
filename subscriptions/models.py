"""SQLAlchemy Core table definitions.

Core tables represent billing entities synced from connectors (Stripe, Lago,
Kill Bill).  Metric tables are owned by individual metrics and prefixed with
``metric_``.  All monetary values use the dual-column convention:
``*_cents`` (original currency) + ``*_base_cents`` (base currency at daily FX rate).
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
    Numeric,
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

product = Table(
    "product",
    metadata,
    Column("id", Text, primary_key=True),
    Column("source_id", Text, ForeignKey("connector_source.id"), nullable=False),
    Column("external_id", Text, nullable=False),
    Column("name", Text),
    Column("description", Text),
    Column("active", Boolean, default=True),
    Column("metadata_", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True)),
    UniqueConstraint("source_id", "external_id", name="uq_product_source"),
)

plan = Table(
    "plan",
    metadata,
    Column("id", Text, primary_key=True),
    Column("source_id", Text, ForeignKey("connector_source.id"), nullable=False),
    Column("external_id", Text, nullable=False),
    Column("product_id", Text, ForeignKey("product.id")),
    Column("name", Text),
    Column("interval", Text, nullable=False),
    Column("interval_count", Integer, nullable=False, default=1),
    Column("amount_cents", BigInteger),
    Column("currency", Text),
    Column("billing_scheme", Text),
    Column("usage_type", Text),
    Column("trial_period_days", Integer),
    Column("metadata_", Text),
    Column("active", Boolean, default=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("source_id", "external_id", name="uq_plan_source"),
)

event_log = Table(
    "event_log",
    metadata,
    Column("id", Text, primary_key=True),
    Column("source_id", Text, ForeignKey("connector_source.id"), nullable=False),
    Column("type", Text, nullable=False),
    Column("customer_id", Text, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=False),
    Column("payload", Text, nullable=False),
)

fx_rate = Table(
    "fx_rate",
    metadata,
    Column("id", Text, primary_key=True),
    Column("date", Date, nullable=False),
    Column("from_currency", Text, nullable=False),
    Column("to_currency", Text, nullable=False),
    Column("rate", Numeric(18, 8), nullable=False),
    Column("source", Text, nullable=False),
    UniqueConstraint("date", "from_currency", "to_currency", name="uq_fx_rate"),
)

invoice = Table(
    "invoice",
    metadata,
    Column("id", Text, primary_key=True),
    Column("source_id", Text, ForeignKey("connector_source.id"), nullable=False),
    Column("external_id", Text, nullable=False),
    Column("customer_id", Text, ForeignKey("customer.id")),
    Column("subscription_id", Text, ForeignKey("subscription.id")),
    Column("status", Text),
    Column("currency", Text),
    Column("subtotal_cents", BigInteger),
    Column("subtotal_base_cents", BigInteger),
    Column("tax_cents", BigInteger),
    Column("tax_base_cents", BigInteger),
    Column("total_cents", BigInteger),
    Column("total_base_cents", BigInteger),
    Column("period_start", DateTime(timezone=True)),
    Column("period_end", DateTime(timezone=True)),
    Column("issued_at", DateTime(timezone=True)),
    Column("paid_at", DateTime(timezone=True)),
    Column("voided_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("source_id", "external_id", name="uq_invoice_source"),
)

invoice_line_item = Table(
    "invoice_line_item",
    metadata,
    Column("id", Text, primary_key=True),
    Column("invoice_id", Text, ForeignKey("invoice.id"), nullable=False),
    Column("subscription_id", Text, ForeignKey("subscription.id")),
    Column("type", Text),
    Column("description", Text),
    Column("amount_cents", BigInteger),
    Column("amount_base_cents", BigInteger),
    Column("currency", Text),
    Column("quantity", Numeric),
    Column("period_start", DateTime(timezone=True)),
    Column("period_end", DateTime(timezone=True)),
)

payment = Table(
    "payment",
    metadata,
    Column("id", Text, primary_key=True),
    Column("source_id", Text, ForeignKey("connector_source.id"), nullable=False),
    Column("external_id", Text, nullable=False),
    Column("invoice_id", Text, ForeignKey("invoice.id")),
    Column("customer_id", Text, ForeignKey("customer.id")),
    Column("status", Text),
    Column("amount_cents", BigInteger),
    Column("amount_base_cents", BigInteger),
    Column("currency", Text),
    Column("payment_method_type", Text),
    Column("failure_reason", Text),
    Column("attempt_count", Integer),
    Column("succeeded_at", DateTime(timezone=True)),
    Column("failed_at", DateTime(timezone=True)),
    Column("refunded_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("source_id", "external_id", name="uq_payment_source"),
)

billable_metric = Table(
    "billable_metric",
    metadata,
    Column("id", Text, primary_key=True),
    Column("source_id", Text, ForeignKey("connector_source.id"), nullable=False),
    Column("code", Text, nullable=False),
    Column("name", Text),
    Column("aggregation_type", Text),
    Column("field_name", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

plan_charge = Table(
    "plan_charge",
    metadata,
    Column("id", Text, primary_key=True),
    Column("plan_id", Text, ForeignKey("plan.id"), nullable=False),
    Column("billable_metric_id", Text, ForeignKey("billable_metric.id")),
    Column("charge_model", Text),
    Column("properties", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
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
    Column("mrr_base_cents", BigInteger, nullable=False, default=0),
    Column("currency", Text),
    Column("quantity", Integer, default=1),
    Column("collection_method", Text),
    Column("cancel_at_period_end", Boolean, default=False),
    Column("cancel_reason", Text),
    Column("cancel_feedback", Text),
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
    Column("mrr_base_cents", BigInteger, nullable=False),
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
    Column("amount_base_cents", BigInteger, nullable=False),
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
    Column("cancel_reason", Text),
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
