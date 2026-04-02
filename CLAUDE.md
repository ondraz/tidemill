# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Open-source subscription analytics engine — transparent, auditable metric computation (MRR, Churn, Retention, LTV) for any billing system. Stripe is the primary integration; Lago and Kill Bill are supported as secondary connectors via same-database mode.

**Current state:** Architecture documentation and deployment infrastructure are complete. Application source code has not been implemented yet.

**Stack:** Python 3.11+ (subscriptions package) + PostgreSQL + Kafka/Redpanda + FastAPI + CLI.

## Repository Structure

```
subscriptions/
├── CLAUDE.md                           # This file
├── README.md                           # Project overview
├── .env.example                        # Environment variables
├── Makefile                            # Development helpers
├── docs/
│   ├── architecture/                   # Implementation plan (source of truth)
│   │   ├── overview.md                 # System design, dual architecture, MVP scope
│   │   ├── database.md                 # PostgreSQL schema, deployment topologies
│   │   ├── events.md                   # Internal event schema, Kafka topics
│   │   ├── metrics.md                  # Metrics (dual-mode computation)
│   │   ├── cubes.md                   # Cubes & query algebra
│   │   ├── connectors.md              # Webhook (Stripe) + database (Lago) connectors
│   │   ├── api.md                      # FastAPI endpoints + CLI interface
│   │   ├── deployment.md              # Docker Compose + Terraform IaC
│   │   └── testing.md                 # Stripe test clocks, seed scripts
│   └── research/                       # Market & competitive analysis
│       ├── *.md                        # Research documents
├── deploy/
│   ├── compose/                        # Docker Compose (PostgreSQL + Redpanda + API + Worker)
│   │   ├── docker-compose.yml
│   │   ├── Dockerfile
│   │   ├── Caddyfile
│   │   └── .env.example
│   ├── domain/                         # Domain registration (Namecheap API)
│   │   ├── domain.sh                   # check / register / set-ns / get-ns
│   │   └── .env.example
│   ├── seed/                           # Stripe test data generation
│   │   ├── stripe_seed.py
│   │   └── stripe_fixtures.json
│   └── terraform/
│       ├── domain/                     # Namecheap → Hetzner nameserver delegation
│       ├── single-server/              # Hetzner single server (~€4/mo)
│       └── kubernetes/                 # k3s HA cluster (~€33/mo)
└── subscriptions/                      # Python package (TO BE IMPLEMENTED)
```

## Key Architecture Decisions

### Dual Architecture

Two integration modes, chosen per billing source:

1. **Ingestion mode** (Stripe) — webhooks translated to internal events via Kafka, stored in analytics-owned PostgreSQL. This is the **primary integration path** and reference implementation.
2. **Same-database mode** (Lago, Kill Bill) — analytics queries the billing engine's PostgreSQL directly. Zero ETL, zero Kafka. Lower priority but strong differentiator for open-source billing users.

### Metrics

Each metric (MRR, Churn, Retention) is a self-contained class (`Metric` subclass) supporting dual modes:
- **Event-driven mode** — consumes Kafka events, maintains materialized tables (Stripe) — primary
- **Direct-query mode** — queries billing tables via `DatabaseConnector` (Lago/Kill Bill) — secondary

### MVP Priorities

**P0:** MRR, Churn (logo + revenue + net revenue), Basic cohort retention, Stripe integration, CLI, FastAPI, Docker deployment (PostgreSQL + Kafka + API + Worker), Documented metric methodology

**P1:** Lago integration, Kill Bill integration, LTV, CAC, Expansion/contraction MRR, Customer segmentation, Web dashboard, Data warehouse export

**Non-goals for V1:** Payment processing, revenue recovery, board-ready reporting, CRM, general-purpose BI

## Navigating the Docs

Start with `docs/architecture/overview.md` for the full system design. Key files:

- **Connectors:** `connectors.md` — `WebhookConnector` (Stripe) vs `DatabaseConnector` (Lago/Kill Bill) patterns
- **Metrics:** `metrics.md` — `Metric` base class, built-in metrics (MRR, Churn, Retention, LTV, Trials) with SQL
- **Query Algebra:** `cubes.md` — Cubes, `QueryFragment` composition, declarative SQL building
- **Database:** `database.md` — Core schema (ER diagram), metric tables, deployment topologies
- **API:** `api.md` — CLI commands, FastAPI endpoints, programmatic Python usage
- **Research:** `docs/research/` — Market analysis, competitive matrix, product positioning

## Package Design (To Be Implemented)

```
subscriptions/
├── __init__.py              # Public API: MetricsEngine, connectors
├── engine.py                # MetricsEngine — routes queries to metrics
├── models.py                # SQLAlchemy models + Pydantic schemas
├── database.py              # Database connection and session management
├── events.py                # Internal event schema (dataclasses)
├── bus.py                   # Kafka producer/consumer
├── state.py                 # Core consumer: events → base tables
├── connectors/
│   ├── __init__.py          # Connector base classes + registry
│   ├── base.py              # WebhookConnector + DatabaseConnector ABCs
│   ├── stripe.py            # Stripe webhook translator — reference implementation
│   ├── lago.py              # Lago database connector (P1)
│   └── killbill.py          # Kill Bill database connector (P1)
├── metrics/
│   ├── __init__.py          # Metric base class + registry
│   ├── query.py             # Cube, QueryFragment, compilation
│   ├── mrr.py               # P0: MRR, ARR, net new MRR
│   ├── churn.py             # P0: Logo, revenue, net revenue churn
│   ├── retention.py         # P0: Cohorts, NRR, GRR
│   ├── ltv.py               # P1: LTV, ARPU
│   └── trials.py            # P1: Trial conversion
├── cli/
│   └── main.py              # CLI entry point
└── api/
    └── app.py               # FastAPI facade
```

## Development Commands

### Deployment (Docker Compose)

```bash
cd deploy/compose

# Full stack (Stripe mode: PostgreSQL + Redpanda + API + Worker)
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

### Lago Companion Mode

```bash
# No Docker required — just pip install and point to Lago's database
pip install subscriptions
export SUBSCRIPTIONS_DATABASE_URL=postgresql://lago:password@postgres/lago
export SUBSCRIPTIONS_CONNECTOR=lago
subscriptions mrr
```

### Test Data

```bash
# Generate Stripe test data via Test Clocks
cd deploy/seed
python stripe_seed.py

# Forward Stripe webhooks locally
stripe listen --forward-to localhost:8000/api/webhooks/stripe

# Cleanup
python stripe_seed.py --cleanup clock_...
```

## Environment Configuration

Copy `.env.example` to `.env` and configure:

- `DATABASE_URL` — PostgreSQL connection string (own DB for Stripe mode, Lago's DB for same-database mode)
- `CONNECTOR` — `stripe`, `lago`, or `killbill`
- `STRIPE_API_KEY` — Stripe API key
- `STRIPE_WEBHOOK_SECRET` — Webhook signing secret
- `KAFKA_BOOTSTRAP_SERVERS` — Kafka/Redpanda address

## Common Workflows

### Adding a New Metric

1. Create `subscriptions/metrics/mymetric.py`
2. Subclass `Metric`, implement `query()` (required) and optionally `handle_event()`, `register_tables()`
3. Decorate with `@register`
4. Document the formula, SQL, assumptions, and edge cases

### Adding a New Billing Connector

**Webhook connector** (for any billing system with webhooks):
1. Create `subscriptions/connectors/myplatform.py`
2. Subclass `WebhookConnector`, implement `translate()` and optionally `backfill()`
3. Decorate with `@register("myplatform")`

**Database connector** (for billing engines with accessible databases):
1. Create `subscriptions/connectors/myplatform.py`
2. Subclass `DatabaseConnector`, implement `get_mrr_cents()`, `get_subscription_changes()`, etc.
3. Decorate with `@register("myplatform")`

## Key Design Conventions

- **Money:** stored as cents (bigint), never float. Dual-column: `*_cents` (original currency) + `*_base_cents` (base currency at daily FX rate, configured via `BASE_CURRENCY`, default USD). Convert to Decimal at query boundary.
- **Dates:** TIMESTAMPTZ in PostgreSQL, `YYYY-MM-DD` in API, `datetime` in Python.
- **Async:** all database access via SQLAlchemy `AsyncSession`/`AsyncEngine`. All metric queries, connector methods, and API endpoints are `async`.
- **Metric transparency:** every metric must document its formula, SQL, assumptions, edge cases.
- **Query Algebra:** all segmented metric SQL is built through `Cube` definitions and composable `QueryFragment` objects (SQLAlchemy `Select`-based, no string concatenation). See `docs/architecture/cubes.md`.
