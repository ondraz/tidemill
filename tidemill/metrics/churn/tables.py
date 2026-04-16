"""Churn metric tables."""

from sqlalchemy import BigInteger, Column, DateTime, Integer, Table, Text, UniqueConstraint

from tidemill.models import metadata

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

metric_churn_active_subscription = Table(
    "metric_churn_active_subscription",
    metadata,
    Column("id", Text, primary_key=True),
    Column("source_id", Text, nullable=False),
    Column("customer_id", Text, nullable=False),
    Column("subscription_id", Text, nullable=False),
    UniqueConstraint(
        "source_id",
        "customer_id",
        "subscription_id",
        name="uq_churn_active_sub",
    ),
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
