"""MRR metric tables."""

from sqlalchemy import BigInteger, Column, Date, DateTime, Index, Table, Text, UniqueConstraint

from tidemill.models import metadata

metric_mrr_snapshot = Table(
    "metric_mrr_snapshot",
    metadata,
    Column("id", Text, primary_key=True),
    Column("source_id", Text, nullable=False),
    Column("customer_id", Text, nullable=False),
    Column("subscription_id", Text, nullable=False),
    # mrr_cents = subscription_mrr_cents + usage_mrr_cents (in original currency).
    # Stored as a single combined column so existing Cube reads keep working.
    Column("mrr_cents", BigInteger, nullable=False),
    Column("mrr_base_cents", BigInteger, nullable=False),
    # Subscription (licensed-recurring) component, persisted separately so the
    # usage recompute can update only its own slice without re-reading Stripe.
    Column("subscription_mrr_cents", BigInteger, nullable=False, default=0),
    Column("subscription_mrr_base_cents", BigInteger, nullable=False, default=0),
    # Usage (metered) component — trailing 3-month average of finalized
    # monthly usage charges. See tidemill/metrics/mrr/usage.py.
    Column("usage_mrr_cents", BigInteger, nullable=False, default=0),
    Column("usage_mrr_base_cents", BigInteger, nullable=False, default=0),
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
    # Origin of the movement: 'subscription' (licensed plan change/lifecycle)
    # or 'usage' (trailing-3m component shifted). Lets the waterfall report
    # split expansion/contraction by source.
    Column("source", Text, nullable=False, default="subscription"),
    Column("amount_cents", BigInteger, nullable=False),
    Column("amount_base_cents", BigInteger, nullable=False),
    Column("currency", Text, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
)

# Per-subscription monthly bucket of finalized usage charges.  Populated when
# an invoice with kind='usage' line items is paid.  The trailing-3m average
# of this table feeds metric_mrr_snapshot.usage_mrr_cents and is the canonical
# raw store for the sibling usage_revenue metric.
metric_mrr_usage_component = Table(
    "metric_mrr_usage_component",
    metadata,
    Column("id", Text, primary_key=True),
    Column("source_id", Text, nullable=False),
    Column("customer_id", Text, nullable=False),
    Column("subscription_id", Text, nullable=False),
    # First day of the UTC month the usage charges were billed for.
    Column("period_start", Date, nullable=False),
    Column("usage_cents", BigInteger, nullable=False),
    Column("usage_base_cents", BigInteger, nullable=False),
    Column("currency", Text, nullable=False),
    Column("computed_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "source_id",
        "subscription_id",
        "period_start",
        name="uq_mrr_usage_component_sub_period",
    ),
    Index(
        "ix_mrr_usage_component_sub_period",
        "source_id",
        "subscription_id",
        "period_start",
    ),
    Index(
        "ix_mrr_usage_component_customer_period",
        "source_id",
        "customer_id",
        "period_start",
    ),
)
