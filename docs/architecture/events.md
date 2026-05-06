# Events

> Internal event schema and Kafka topics.
> Last updated: March 2026

## Overview

Every change in a billing system is translated by a [connector](connectors.md) into an internal event, published to Kafka, and consumed by the core state manager and [metrics](metrics.md).

Internal events are the single source of truth for the ingestion architecture (Stripe). They are immutable, ordered, and replayable.

!!! note "Same-database mode (Lago, Kill Bill)"
    When using same-database connectors, metrics query the billing engine's PostgreSQL directly and do not consume Kafka events. The event schema below applies to ingestion-mode connectors (Stripe and any future webhook-based connector). See [Connectors](connectors.md) for details.

## Event Envelope

Every event has the same envelope:

```python
@dataclass(frozen=True)
class Event:
    id: UUID                    # unique event ID (idempotency key)
    source_id: UUID             # which connector_source produced this
    type: str                   # e.g. "subscription.activated"
    occurred_at: datetime       # when it happened in the billing system
    published_at: datetime      # when we published to Kafka
    customer_id: str            # external customer ID (Kafka partition key)
    payload: dict               # type-specific data (see below)
```

`customer_id` is the Kafka partition key. All events for a given customer land on the same partition, preserving ordering per customer.

## Event Types

### Customer Events

| Type | Trigger | Payload |
|------|---------|---------|
| `customer.created` | New customer in billing system | `{external_id, name, email, currency, country, metadata}` |
| `customer.updated` | Customer details changed | `{external_id, changed_fields}` |
| `customer.deleted` | Customer removed | `{external_id}` |

### Subscription Events

The most important events for metric computation.

| Type | Trigger | Payload |
|------|---------|---------|
| `subscription.created` | New subscription | `{external_id, customer_external_id, plan_external_id, status, mrr_cents, quantity, started_at, trial_start, trial_end, current_period_start, current_period_end}` |
| `subscription.activated` | Trial → active, or pending → active | `{external_id, mrr_cents}` |
| `subscription.changed` | Plan or quantity changed | `{external_id, prev_plan_external_id, new_plan_external_id, prev_mrr_cents, new_mrr_cents, prev_quantity, new_quantity}` |
| `subscription.canceled` | Subscription set to cancel at period end | `{external_id, mrr_cents, canceled_at, ends_at, cancel_reason}` |
| `subscription.churned` | Subscription ended (no longer active) | `{external_id, prev_mrr_cents, cancel_reason}` |
| `subscription.reactivated` | Previously churned customer re-subscribes | `{external_id, mrr_cents}` |
| `subscription.trial_started` | Free trial begins | `{external_id, trial_start, trial_end}` |
| `subscription.trial_converted` | Trial → paid | `{external_id, mrr_cents}` |
| `subscription.trial_expired` | Trial ended without conversion | `{external_id}` |
| `subscription.paused` | Subscription paused | `{external_id, mrr_cents}` |
| `subscription.resumed` | Subscription resumed from pause | `{external_id, mrr_cents}` |

**MRR classification:** The difference between `prev_mrr_cents` and `new_mrr_cents` in `subscription.changed` determines whether it's expansion (new > prev) or contraction (new < prev). The MRR metric uses this to compute net new MRR breakdown.

### Invoice Events

| Type | Trigger | Payload |
|------|---------|---------|
| `invoice.created` | New invoice generated | `{external_id, customer_external_id, subscription_external_id, status, currency, subtotal_cents, tax_cents, total_cents, period_start, period_end, line_items[]}` |
| `invoice.paid` | Invoice payment succeeded | `{external_id, paid_at, amount_cents}` |
| `invoice.voided` | Invoice canceled | `{external_id, voided_at}` |
| `invoice.uncollectible` | Invoice marked uncollectible | `{external_id}` |

### Payment Events

| Type | Trigger | Payload |
|------|---------|---------|
| `payment.succeeded` | Payment completed | `{external_id, invoice_external_id, customer_external_id, amount_cents, currency, payment_method_type}` |
| `payment.failed` | Payment attempt failed | `{external_id, invoice_external_id, customer_external_id, amount_cents, failure_reason, attempt_count}` |
| `payment.refunded` | Payment refunded | `{external_id, amount_cents, refunded_at}` |

### Usage Events

| Type | Trigger | Payload |
|------|---------|---------|
| `usage.recorded` | Usage data received | `{customer_external_id, subscription_external_id, metric_code, quantity, properties, timestamp}` |

### Expense-side Events (QuickBooks Online et al.)

These are emitted by `ExpenseConnector` subclasses (today: QuickBooks Online; future: Xero, FreshBooks, Wave, Sage). For these events `Event.customer_id` carries the **realm/tenant ID** of the accounting source so events for the same QBO company stay on one Kafka partition.

| Type | Trigger | Payload |
|------|---------|---------|
| `vendor.created` | Vendor created in source | `{external_id, name, email, country, currency, active, metadata}` |
| `vendor.updated` | Vendor edited | Same fields as `vendor.created` |
| `vendor.deleted` | Vendor deleted | `{external_id}` |
| `account.created` | Chart-of-accounts entry created | `{external_id, name, account_type, account_subtype, parent_external_id, currency, active, metadata}` |
| `account.updated` | Account edited | Same fields as `account.created` |
| `bill.created` | New A/P bill | `{external_id, vendor_external_id, status, doc_number, currency, subtotal_cents, tax_cents, total_cents, txn_date, due_date, memo, lines: [{account_external_id, description, amount_cents, currency, dimensions}]}` |
| `bill.updated` | Bill modified | Same shape as `bill.created` |
| `bill.paid` | Bill marked paid | `{external_id, paid_at}` |
| `bill.voided` | Bill voided | `{external_id, voided_at}` |
| `expense.created` | Direct purchase recorded | `{external_id, vendor_external_id, payment_type, doc_number, currency, total_cents, txn_date, memo, lines: [...]}` |
| `expense.updated` | Direct purchase edited | Same shape as `expense.created` |
| `expense.voided` | Direct purchase voided | `{external_id, voided_at}` |
| `bill_payment.created` | Payment applied to a bill | `{external_id, bill_external_id, paid_at, amount_cents, currency}` |

`account_type` is one of the canonical enums (see [expenses.md](expenses.md#canonical-enums)). Native source values are preserved on `metadata`.

## Kafka Topics

| Topic | Partition Key | Description |
|-------|--------------|-------------|
| `tidemill.events` | `customer_id` | All internal events (single topic) |
| `tidemill.events.dlq` | `customer_id` | Dead letter queue for failed processing |

A single topic keeps event ordering simple. Consumers use the `type` field to filter.

For high-volume deployments, events can be split into separate topics per entity type (`tidemill.events.subscription`, `tidemill.events.invoice`, etc.) at the cost of weaker cross-entity ordering guarantees.

## Consumer Groups

| Group | Consumes | Purpose |
|-------|----------|---------|
| `tidemill.state` | All events | Updates core PostgreSQL tables (current state) |
| `tidemill.metric.mrr` | `subscription.*` | MRR metric |
| `tidemill.metric.churn` | `subscription.*`, `customer.*` | Churn metric |
| `tidemill.metric.retention` | `subscription.*`, `customer.*` | Retention metric |
| `tidemill.metric.ltv` | `subscription.*`, `invoice.*`, `payment.*` | LTV metric |
| `tidemill.metric.trials` | `subscription.trial_*`, `subscription.activated` | Trials metric |

Each metric runs in its own consumer group, so it maintains its own offset. This means:

- Metrics process events independently (a slow metric doesn't block others)
- A new metric can be added and replayed from offset 0 to backfill
- A metric can be reset (seek to beginning) to recompute from scratch

## Idempotency

Events carry a unique `id` (UUID). Consumers must be idempotent — processing the same event twice produces the same result. This is enforced by:

1. Storing the last processed `event.id` per consumer group
2. Using `INSERT ... ON CONFLICT DO NOTHING` for append-only tables
3. Using `INSERT ... ON CONFLICT DO UPDATE` for current-state tables

## Event Persistence

Events are persisted in two places:

1. **Kafka** — the primary log, retained for a configurable period (default: 30 days)
2. **PostgreSQL `event_log` table** — permanent archive for replay and audit

```sql
CREATE TABLE event_log (
    id          UUID PRIMARY KEY,
    source_id   UUID NOT NULL REFERENCES connector_source(id),
    type        TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    payload     JSONB NOT NULL
);

CREATE INDEX ix_event_log_type_time ON event_log(type, occurred_at);
CREATE INDEX ix_event_log_customer ON event_log(customer_id, occurred_at);
```

When Kafka retention expires, or when bootstrapping a new deployment, the `event_log` table is the replay source.

## Dead-Letter Handling

Whenever a consumer's `handle_event` raises, the event is recorded in the
`dead_letter_event` table (one row per `(event_id, consumer)` pair) and
mirrored to the Kafka DLQ topic. The offset is then committed so the
worker keeps making progress instead of getting stuck on the bad event.

The most common case is `FxRateMissingError` — an MRR / LTV event whose
currency has no `fx_rate` row yet. Once you backfill the rate:

```bash
tidemill dlq-list --error-type fx_rate_missing      # confirm what's queued
tidemill dlq-replay --error-type fx_rate_missing    # republish to Kafka
```

The worker reprocesses the events normally; on success the consumer
sets `dead_letter_event.resolved_at` so the rows drop out of the
default `dlq-list` view.

```sql
CREATE TABLE dead_letter_event (
    id               TEXT PRIMARY KEY,
    event_id         TEXT NOT NULL,
    source_id        TEXT NOT NULL,
    event_type       TEXT NOT NULL,
    consumer         TEXT NOT NULL,        -- 'state', 'metric:mrr', …
    error_type       TEXT NOT NULL,        -- 'fx_rate_missing', 'unknown', …
    error_message    TEXT NOT NULL,
    payload          JSONB NOT NULL,
    occurred_at      TIMESTAMPTZ NOT NULL,
    dead_lettered_at TIMESTAMPTZ NOT NULL,
    resolved_at      TIMESTAMPTZ,
    UNIQUE (event_id, consumer)
);
```
