"""LTV metric tables."""

from sqlalchemy import BigInteger, Column, DateTime, Table, Text

from tidemill.models import metadata

metric_ltv_invoice = Table(
    "metric_ltv_invoice",
    metadata,
    Column("id", Text, primary_key=True),
    Column("event_id", Text, nullable=False, unique=True),
    Column("source_id", Text, nullable=False),
    Column("customer_id", Text, nullable=False),
    Column("amount_cents", BigInteger, nullable=False),
    Column("amount_base_cents", BigInteger, nullable=False),
    Column("currency", Text, nullable=False),
    Column("paid_at", DateTime(timezone=True), nullable=False),
)
