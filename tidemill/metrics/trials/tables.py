"""Trials metric tables."""

from sqlalchemy import Column, DateTime, Table, Text

from tidemill.models import metadata

metric_trial_event = Table(
    "metric_trial_event",
    metadata,
    Column("id", Text, primary_key=True),
    Column("event_id", Text, nullable=False, unique=True),
    Column("source_id", Text, nullable=False),
    Column("customer_id", Text, nullable=False),
    Column("subscription_id", Text, nullable=False),
    Column("event_type", Text, nullable=False),  # started | converted | expired
    Column("occurred_at", DateTime(timezone=True), nullable=False),
)
