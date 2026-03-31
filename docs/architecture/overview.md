# Architecture Overview

> Implementation plan for the open-source subscription analytics engine.
> Last updated: March 2026

## Positioning

Open-source subscription analytics with transparent, auditable, customizable metric computation. Works with any billing system — Stripe, Lago, Kill Bill — and supports self-hosting.

> ChartMogul, Baremetrics, and ProfitWell all compute your metrics in a black box. This project gives you the formulas, the SQL, and the code — reviewable, forkable, contributable.

### Target Users (Priority Order)

1. **Stripe users** — largest installed base, no open-source analytics option exists
2. **Self-hosting mandates** — regulated industries, privacy-conscious organizations
3. **Metric customizers** — complex billing models (usage-based, hybrid) that SaaS analytics tools can't handle
4. **Open-source billing users** (Lago, Kill Bill) — philosophical alignment, deeper integration possible
5. **Cost-conscious startups** — free alternative to ChartMogul/Baremetrics

## Design Principles

1. **Metrics package first** — the core is a Python library (`subscriptions`), not a web app. FastAPI and CLI are thin facades. You can `import subscriptions` in a Jupyter notebook and query metrics directly.
2. **Stripe-first, dual architecture** — the primary integration path is **ingestion mode**: Stripe webhooks translated into internal events, published to Kafka, consumed by metrics. A secondary **same-database mode** is available for open-source billing engines (Lago, Kill Bill) that expose their PostgreSQL — zero ETL, but lower priority.
3. **Metrics are self-contained** — each metric (MRR, churn, retention, ...) is a `Metric` subclass that declares its database tables, registers itself, and handles both event-driven and direct-query modes.
4. **Transparent computation** — every metric has documented, auditable, forkable logic. Metric definitions are code: reviewable, contributable, no black boxes. This is the core differentiator vs. ChartMogul, Baremetrics, and ProfitWell.
5. **Connectors** — billing systems are data sources. Webhook connectors translate vendor events into internal events; database connectors query billing tables directly. Adding a new billing source means implementing one adapter.
6. **Self-hostable** — PostgreSQL + Kafka + Docker. For open-source billing engines with accessible databases (Lago, Kill Bill), Kafka can be omitted in favour of direct database queries.

## System Architecture

The system supports two integration architectures, chosen per billing source:

### Mode A: Ingestion (Stripe) — Primary

```
Billing System        Event Bus          Analytics Engine           Consumers
┌─────────┐ webhooks  ┌─────────┐       ┌──────────────────────┐
│  Stripe ├──────────►│         │       │  subscriptions (Py)  │     ┌──────────┐
│         │           │  Kafka  ├──────►│                      ├────►│   CLI    │
└─────────┘           │         │       │  ┌────────────────┐  │     └──────────┘
                      └─────────┘       │  │    Metrics     │  │     ┌──────────┐
   connector translates                 │  │ MRR│Churn│Ret… │  ├────►│  FastAPI │
   webhook → internal event             │  └────────────────┘  │     └──────────┘
   → publishes to Kafka                 │  ┌────────────────┐  │     ┌──────────┐
                                        │  │   PostgreSQL   │  ├────►│ Jupyter  │
                                        │  │  (analytics)   │  │     └──────────┘
                                        │  └────────────────┘  │
                                        └──────────────────────┘
```

**Data flow (ingestion):**

1. Billing system sends a webhook (e.g., Stripe `customer.subscription.updated`)
2. **Webhook connector** receives it, translates to an internal event (e.g., `subscription.activated`), publishes to Kafka
3. **Core consumer** updates base tables (customer, subscription, invoice, ...) — the current-state view
4. **Metrics** each consume the events they care about and update their own materialized tables
5. **Consumers** (CLI, API, Jupyter) query metrics for computed results

This is the **primary integration path** — it works with any billing system that exposes webhooks. Stripe is the reference implementation.

### Mode B: Same-Database (Lago, Kill Bill) — Alternative

```
Billing Engine (Lago/Kill Bill)        Analytics Engine              Consumers
┌───────────────────────────┐       ┌──────────────────────┐
│        PostgreSQL         │       │  subscriptions (Py)  │     ┌──────────┐
│  ┌─────────────────────┐  │       │                      ├────►│   CLI    │
│  │ subscriptions, fees, │◄─ ─ ─ ─┤  ┌────────────────┐  │     └──────────┘
│  │ invoices, customers  │  │ SQL  │  │    Metrics │  │     ┌──────────┐
│  └─────────────────────┘  │ query │  │ MRR│Churn│Ret… │  ├────►│  FastAPI │
│  ┌─────────────────────┐  │       │  └────────────────┘  │     └──────────┘
│  │ metric_* tables      │◄─ ─ ─ ─┤                      │     ┌──────────┐
│  │ (analytics-owned)    │  │       │                      ├────►│ Jupyter  │
│  └─────────────────────┘  │       └──────────────────────┘     └──────────┘
└───────────────────────────┘
     Zero ETL. Zero latency.
     No Kafka needed.
```

**Data flow (same-database):**

1. Lago/Kill Bill writes billing data to PostgreSQL as part of normal operation
2. **Database connector** reads billing tables directly via SQL (subscriptions, fees, invoices)
3. **Metrics** query billing tables on demand or materialize into `metric_*` tables in the same database
4. **Consumers** (CLI, API, Jupyter) query metrics for computed results

For open-source billing engines that expose their PostgreSQL, this eliminates the ETL layer entirely. No Kafka required. This mode is a secondary priority but a strong differentiator for Lago and Kill Bill users.

## Package Structure

```
subscriptions/
├── __init__.py              # Public API: MetricsEngine, connectors
├── engine.py                # MetricsEngine — routes queries to metrics
├── models.py                # SQLAlchemy models + Pydantic schemas
├── database.py              # Database connection and session management
├── events.py                # Internal event schema (dataclasses)
├── bus.py                   # Kafka producer/consumer wrappers (ingestion mode only)
├── state.py                 # Core consumer: events → base tables (ingestion mode only)
├── connectors/
│   ├── __init__.py          # Connector base classes + registry
│   ├── base.py              # WebhookConnector + DatabaseConnector ABCs
│   ├── stripe.py            # Stripe webhook translator — reference implementation
│   ├── lago.py              # Lago database connector (same-database mode)
│   └── killbill.py          # Kill Bill database connector (same-database mode)
├── metrics/
│   ├── __init__.py          # Metric base class + registry
│   ├── mrr.py               # P0: MRR (MRR, ARR, net new MRR)
│   ├── churn.py             # P0: Churn (logo, revenue, net revenue)
│   ├── retention.py         # P0: Retention (cohorts, NRR, GRR)
│   ├── ltv.py               # P1: LTV (LTV, ARPU)
│   └── trials.py            # P1: Trials (conversion rate)
├── cli/
│   ├── __init__.py
│   └── main.py              # CLI entry point (P0)
└── api/
    ├── __init__.py
    └── app.py               # FastAPI facade
```

## Technology Choices

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python 3.11+ | Data science ecosystem, Jupyter integration |
| Database | PostgreSQL | See [Database](database.md) |
| Message bus | Kafka (ingestion mode only) | Durable, replayable, ordered per partition |
| ORM | SQLAlchemy 2.0 | Async support, mature, works with Alembic |
| Migrations | Alembic | Standard for SQLAlchemy projects |
| API | FastAPI | Async, auto-docs, Pydantic integration |
| CLI | Click or Typer | Standard Python CLI tooling |
| Packaging | uv + pyproject.toml | Fast, modern Python tooling |

## Why Kafka

Kafka is the backbone of the primary integration path (Stripe and any webhook-based connector). Same-database mode (Lago, Kill Bill) can bypass Kafka by querying billing tables directly.

Kafka gives us properties that a simple in-process event bus cannot:

- **Durability** — events survive process restarts. If a metric crashes, it resumes from its last offset.
- **Replay** — add a new metric and replay the full event history to backfill its tables from scratch.
- **Decoupling** — connectors, core state, and metrics run independently. A slow metric doesn't block webhook processing.
- **Ordering** — events for a given customer are ordered within a partition (partition by `customer_id`).

For development and single-node deployments, [Redpanda](https://redpanda.com/) is a Kafka-compatible alternative with simpler operations (~256 MB RAM vs 1-2 GB for Kafka).

## MVP Scope

### P0 (Must-Have)

- **MRR computation** with transparent, documented, configurable logic
- **Churn calculation** — logo churn, revenue churn, net revenue churn
- **Basic cohort analysis** — monthly retention cohorts
- **Stripe integration** via webhooks + Kafka — reference implementation (largest installed base)
- **CLI** for programmatic access to metrics
- **FastAPI** for HTTP access
- **Self-hosted deployment** via Docker (PostgreSQL + Kafka + API + Worker)
- **Documented metric methodology** — every formula explained and auditable

### P1 (Nice-to-Have)

- Lago integration via direct PostgreSQL access (same-database mode)
- Kill Bill integration
- LTV and CAC computation
- Expansion/contraction MRR breakdown
- Customer segmentation
- Web dashboard UI
- Data warehouse export
- Trial conversion tracking

### Non-Goals for V1

- Payment processing
- Revenue recovery / dunning
- Board-ready financial reporting
- CRM features
- Multi-scenario planning
- General-purpose BI

## What's Next

- [Events](events.md) — internal event schema and Kafka topics
- [Database](database.md) — core tables, ER diagram, deployment topologies
- [Connectors](connectors.md) — webhook translators (Stripe) and database connectors (Lago, Kill Bill)
- [Metrics](metrics.md) — metric base class, built-in metrics (dual-mode)
- [API](api.md) — FastAPI endpoints and CLI interface
