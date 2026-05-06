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
    Index,
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

# Per-consumer dead-letter table.  Worker tasks insert one row whenever
# ``handle_event`` raises — keeps the failed event payload around so it
# can be replayed once the underlying issue (e.g. a missing fx_rate row)
# is resolved.  ``(event_id, consumer)`` is unique so each metric stream
# tracks its own failures independently.
dead_letter_event = Table(
    "dead_letter_event",
    metadata,
    Column("id", Text, primary_key=True),
    Column("event_id", Text, nullable=False),
    Column("source_id", Text, nullable=False),
    Column("event_type", Text, nullable=False),
    Column("consumer", Text, nullable=False),
    Column("error_type", Text, nullable=False),
    Column("error_message", Text, nullable=False),
    Column("payload", Text, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("dead_lettered_at", DateTime(timezone=True), nullable=False),
    Column("resolved_at", DateTime(timezone=True)),
    UniqueConstraint("event_id", "consumer", name="uq_dlq_event_consumer"),
    Index("ix_dlq_unresolved", "consumer", "error_type", "resolved_at"),
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
    Column("plan_id", Text, ForeignKey("plan.id")),
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

# ── Customer attributes & segments ──────────────────────────────────────
# Workspace-scoped, not user-scoped — segments and attributes are shared
# across all users in a Tidemill deployment.  The `segment` table mirrors
# the saved_chart JSON-config pattern in models_auth.py.

attribute_definition = Table(
    "attribute_definition",
    metadata,
    Column("key", Text, primary_key=True),
    Column("label", Text, nullable=False),
    # 'string' | 'number' | 'boolean' | 'timestamp'
    Column("type", Text, nullable=False),
    # 'stripe' | 'csv' | 'api' | 'computed'
    Column("source", Text, nullable=False),
    Column("description", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True)),
)

customer_attribute = Table(
    "customer_attribute",
    metadata,
    Column("id", Text, primary_key=True),
    Column("source_id", Text, nullable=False),
    Column("customer_id", Text, nullable=False),
    Column("key", Text, ForeignKey("attribute_definition.key"), nullable=False),
    Column("value_string", Text),
    Column("value_number", Numeric),
    Column("value_bool", Boolean),
    Column("value_timestamp", DateTime(timezone=True)),
    # Origin is the source that wrote this value, e.g. 'stripe', 'csv', 'api'.
    # Not the same as attribute_definition.source — a 'stripe' attribute may
    # later be overridden by an 'api' upsert; origin records the last writer.
    Column("origin", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("source_id", "customer_id", "key", name="uq_customer_attr_source_cust_key"),
    Index("ix_customer_attr_key_customer", "key", "source_id", "customer_id"),
)

segment = Table(
    "segment",
    metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False, unique=True),
    Column("description", Text),
    # JSON-encoded SegmentDef (see tidemill.segments.model).
    Column("definition", Text, nullable=False),
    # Nullable + no CASCADE — segments outlive their creator (workspace-shared).
    Column("created_by", Text, ForeignKey("app_user.id")),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True)),
)

# ── Expense entities (vendors, chart of accounts, bills, expenses) ──────
# Platform-neutral schema designed to accept QuickBooks Online, Xero,
# FreshBooks, Wave, Sage, etc. Connectors normalize their native vocabulary
# into the canonical enums documented in docs/architecture/expenses.md.
# Native values are preserved in metadata_ for traceability.

vendor = Table(
    "vendor",
    metadata,
    Column("id", Text, primary_key=True),
    Column("source_id", Text, ForeignKey("connector_source.id"), nullable=False),
    Column("external_id", Text, nullable=False),
    Column("name", Text),
    Column("email", Text),
    Column("country", Text),
    Column("currency", Text),
    Column("active", Boolean, default=True),
    Column("metadata_", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True)),
    UniqueConstraint("source_id", "external_id", name="uq_vendor_source"),
)

# Chart of Accounts. account_type ∈ {expense, cogs, income, asset, liability,
# equity, other} — covers the GAAP/IFRS structure exposed by every accounting
# platform we target. The original native type is kept in metadata_.
account = Table(
    "account",
    metadata,
    Column("id", Text, primary_key=True),
    Column("source_id", Text, ForeignKey("connector_source.id"), nullable=False),
    Column("external_id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("account_type", Text, nullable=False),
    Column("account_subtype", Text),
    Column("parent_external_id", Text),
    Column("currency", Text),
    Column("active", Boolean, default=True),
    Column("metadata_", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True)),
    UniqueConstraint("source_id", "external_id", name="uq_account_source"),
    Index("ix_account_type", "source_id", "account_type"),
)

# Accrual-side payable. status ∈ {open, partial, paid, voided}.
bill = Table(
    "bill",
    metadata,
    Column("id", Text, primary_key=True),
    Column("source_id", Text, ForeignKey("connector_source.id"), nullable=False),
    Column("external_id", Text, nullable=False),
    Column("vendor_id", Text, ForeignKey("vendor.id")),
    Column("status", Text, nullable=False),
    Column("doc_number", Text),
    Column("currency", Text),
    Column("subtotal_cents", BigInteger),
    Column("subtotal_base_cents", BigInteger),
    Column("tax_cents", BigInteger),
    Column("tax_base_cents", BigInteger),
    Column("total_cents", BigInteger),
    Column("total_base_cents", BigInteger),
    Column("txn_date", DateTime(timezone=True)),
    Column("due_date", DateTime(timezone=True)),
    Column("paid_at", DateTime(timezone=True)),
    Column("voided_at", DateTime(timezone=True)),
    Column("memo", Text),
    Column("metadata_", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True)),
    UniqueConstraint("source_id", "external_id", name="uq_bill_source"),
    Index("ix_bill_vendor_date", "vendor_id", "txn_date"),
)

bill_line = Table(
    "bill_line",
    metadata,
    Column("id", Text, primary_key=True),
    Column("bill_id", Text, ForeignKey("bill.id"), nullable=False),
    Column("account_id", Text, ForeignKey("account.id")),
    Column("description", Text),
    Column("quantity", Numeric),
    Column("amount_cents", BigInteger),
    Column("amount_base_cents", BigInteger),
    Column("currency", Text),
    # JSON-encoded cross-cutting tagging (project / class / department /
    # tracking_category) — abstracts the per-platform taxonomy so future
    # connectors can plug in without schema changes.
    Column("dimensions", Text),
    Index("ix_bill_line_account", "account_id"),
)

# Direct cash/credit/check expense — no bill intermediary.
# payment_type ∈ {cash, credit_card, check, bank_transfer, other}.
expense = Table(
    "expense",
    metadata,
    Column("id", Text, primary_key=True),
    Column("source_id", Text, ForeignKey("connector_source.id"), nullable=False),
    Column("external_id", Text, nullable=False),
    Column("vendor_id", Text, ForeignKey("vendor.id")),
    Column("payment_type", Text, nullable=False),
    Column("doc_number", Text),
    Column("currency", Text),
    Column("subtotal_cents", BigInteger),
    Column("subtotal_base_cents", BigInteger),
    Column("tax_cents", BigInteger),
    Column("tax_base_cents", BigInteger),
    Column("total_cents", BigInteger),
    Column("total_base_cents", BigInteger),
    Column("txn_date", DateTime(timezone=True)),
    Column("voided_at", DateTime(timezone=True)),
    Column("memo", Text),
    Column("metadata_", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True)),
    UniqueConstraint("source_id", "external_id", name="uq_expense_source"),
    Index("ix_expense_vendor_date", "vendor_id", "txn_date"),
)

expense_line = Table(
    "expense_line",
    metadata,
    Column("id", Text, primary_key=True),
    Column("expense_id", Text, ForeignKey("expense.id"), nullable=False),
    Column("account_id", Text, ForeignKey("account.id")),
    Column("description", Text),
    Column("quantity", Numeric),
    Column("amount_cents", BigInteger),
    Column("amount_base_cents", BigInteger),
    Column("currency", Text),
    Column("dimensions", Text),
    Index("ix_expense_line_account", "account_id"),
)

bill_payment = Table(
    "bill_payment",
    metadata,
    Column("id", Text, primary_key=True),
    Column("source_id", Text, ForeignKey("connector_source.id"), nullable=False),
    Column("external_id", Text, nullable=False),
    Column("bill_id", Text, ForeignKey("bill.id")),
    Column("paid_at", DateTime(timezone=True)),
    Column("amount_cents", BigInteger),
    Column("amount_base_cents", BigInteger),
    Column("currency", Text),
    Column("metadata_", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("source_id", "external_id", name="uq_bill_payment_source"),
)

# Metric tables are defined in each metric's own tables.py module.
# Importing the metrics package triggers registration on this shared metadata.
import tidemill.metrics  # noqa: E402, F401

# Auth, dashboard, and chart tables.
import tidemill.models_auth  # noqa: E402, F401
