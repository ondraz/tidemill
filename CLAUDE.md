# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Open-source subscription analytics engine — transparent, auditable metric computation (MRR, Churn, Retention, LTV) for any billing system. Stripe is the primary integration; Lago and Kill Bill are supported as secondary connectors via same-database mode.

**Current state:** Core application implemented — connectors (Stripe), metrics (MRR, Churn, Retention, LTV, Trials), event pipeline, query algebra, FastAPI, and deployment infrastructure. Lago/Kill Bill connectors are P1.

**Stack:** Python 3.11+ (tidemill package) + PostgreSQL + Kafka/Redpanda + FastAPI + CLI.

## Repository Structure

```
tidemill/
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
│   │   ├── cubes.md                    # Cubes & query algebra
│   │   ├── connectors.md               # Webhook (Stripe) + database (Lago) connectors
│   │   ├── api.md                      # FastAPI endpoints + CLI interface
│   ├── development/                    # Local development setup, testing, deployment
│   │   ├── development.md              # Local development environment setup
│   │   └── testing.md                  # Test data generation, seed scripts
│   │   ├── deployment.md               # Docker Compose + Terraform IaC
│   └── research/                       # Market & competitive analysis
│       ├── *.md                        # Research documents
├── deploy/
│   ├── compose/                        # Docker Compose (PostgreSQL + Redpanda + API + Worker)
│   │   ├── docker-compose.yml
│   │   ├── Dockerfile
│   │   ├── Caddyfile
│   │   └── .env.example
│   ├── seed/                           # Stripe test data generation
│   │   ├── stripe_seed.py
│   │   └── stripe_fixtures.json
│   └── terraform/
│       ├── single-server/              # Hetzner single server (~€4/mo)
│       └── kubernetes/                 # k3s HA cluster (~€33/mo)
└── tidemill/                           # Python package (TO BE IMPLEMENTED)
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

**P1 (implemented):** LTV, Trials

**P1 (remaining):** Lago integration, Kill Bill integration, CAC, Customer segmentation, Web dashboard, Data warehouse export

**Non-goals for V1:** Payment processing, revenue recovery, board-ready reporting, CRM, general-purpose BI

## Navigating the Docs

Start with `docs/architecture/overview.md` for the full system design. Key files:

- **Connectors:** `connectors.md` — `WebhookConnector` (Stripe) vs `DatabaseConnector` (Lago/Kill Bill) patterns
- **Metrics:** `metrics.md` — `Metric` base class, built-in metrics (MRR, Churn, Retention, LTV, Trials) with SQL
- **Query Algebra:** `cubes.md` — Cubes, `QueryFragment` composition, declarative SQL building
- **Database:** `database.md` — Core schema (ER diagram), metric tables, deployment topologies
- **API:** `api.md` — CLI commands, FastAPI endpoints, programmatic Python usage
- **Research:** `docs/research/` — Market analysis, competitive matrix, product positioning

## Package Structure

```
tidemill/
├── engine.py                # MetricsEngine — routes queries to metrics
├── models.py                # SQLAlchemy Core tables (billing entities)
├── events.py                # Internal event schema (dataclasses)
├── fx.py                    # Foreign exchange rate conversion
├── bus.py                   # Kafka producer/consumer
├── state.py                 # Core consumer: events → base tables
├── connectors/
│   ├── base.py              # WebhookConnector + DatabaseConnector ABCs
│   ├── stripe.py            # Stripe webhook translator
│   ├── lago.py              # Lago database connector (P1)
│   └── killbill.py          # Kill Bill database connector (P1)
├── metrics/
│   ├── base.py              # Metric ABC + QuerySpec
│   ├── registry.py          # @register decorator, discovery, dependency resolution
│   ├── query.py             # Cube, QueryFragment, compilation
│   ├── route_helpers.py     # Shared FastAPI helpers
│   ├── mrr/                 # MRR, ARR, net new MRR, waterfall
│   ├── churn/               # Logo churn, revenue churn
│   ├── retention/           # Cohort retention, NRR, GRR
│   ├── ltv/                 # LTV, ARPU, cohort LTV
│   └── trials/              # Trial conversion rate, funnel
├── cli/
│   └── main.py              # CLI entry point
├── api/
│   └── app.py               # FastAPI application
└── reports/                 # Analytical reports & Stripe validation
    ├── _style.py            # Shared colours, formatters, rcParams
    ├── mrr.py               # MRR: comparison, breakdown, waterfall, trend
    ├── churn.py             # Churn: overview, timeline, lost MRR
    ├── retention.py         # Retention: heatmap, curve, NRR/GRR
    ├── ltv.py               # LTV: overview, ARPU timeline, cohort
    ├── trials.py            # Trials: funnel, timeline
    └── stripecheck/         # Stripe data layer & ground-truth validation
        ├── tidemill_client.py   # Tidemill REST API client
        ├── stripe_data.py       # Lazy-loading Stripe subscription fetcher
        ├── stripe_metrics.py    # Ground-truth metrics from raw Stripe data
        └── compare.py           # Side-by-side Tidemill vs Stripe comparison
```

Each metric module: `tables.py` (schema), `cubes.py` (query model), `metric.py` (logic), `routes.py` (API), `__init__.py`.

### Reports & Stripe Validation

`tidemill.reports` provides pre-built charts and summaries for every metric. `tidemill.reports.stripecheck` is the data layer — it fetches from the Stripe API, computes ground-truth metrics, and compares them with Tidemill's event-driven results.

```python
from tidemill import reports
from tidemill.reports.stripecheck import TidemillClient, StripeData

reports.setup()
tm = TidemillClient()   # reads TIDEMILL_API env var
sd = StripeData()        # uses stripe.api_key

# One-liner reports (print summary + display chart + return data)
reports.mrr.comparison(tm, sd, at="2026-03-01")
reports.mrr.waterfall(tm, "2025-09-01", "2026-04-30")
reports.churn.overview(tm, sd, "2025-10-01", "2026-03-31")
reports.retention.heatmap(sd, "2025-09-01", "2026-03-31")
```

The notebooks in `docs/notebooks/` use this library — each code cell is a single report call.

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
pip install tidemill
export TIDEMILL_DATABASE_URL=postgresql://lago:password@postgres/lago
export TIDEMILL_CONNECTOR=lago
tidemill mrr
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

1. Create `tidemill/metrics/mymetric.py`
2. Subclass `Metric`, implement `query()` (required) and optionally `handle_event()`, `register_tables()`
3. Decorate with `@register`
4. Document the formula, SQL, assumptions, and edge cases

### Adding a New Billing Connector

**Webhook connector** (for any billing system with webhooks):
1. Create `tidemill/connectors/myplatform.py`
2. Subclass `WebhookConnector`, implement `translate()` and optionally `backfill()`
3. Decorate with `@register("myplatform")`

**Database connector** (for billing engines with accessible databases):
1. Create `tidemill/connectors/myplatform.py`
2. Subclass `DatabaseConnector`, implement `get_mrr_cents()`, `get_subscription_changes()`, etc.
3. Decorate with `@register("myplatform")`

## Key Design Conventions

- **Money:** stored as cents (bigint), never float. Dual-column: `*_cents` (original currency) + `*_base_cents` (base currency at daily FX rate, configured via `BASE_CURRENCY`, default USD). Convert to Decimal at query boundary.
- **Dates:** TIMESTAMPTZ in PostgreSQL, `YYYY-MM-DD` in API, `datetime` in Python.
- **Async:** all database access via SQLAlchemy `AsyncSession`/`AsyncEngine`. All metric queries, connector methods, and API endpoints are `async`.
- **Metric transparency:** every metric must document its formula, SQL, assumptions, edge cases.
- **Query Algebra:** all segmented metric SQL is built through `Cube` definitions and composable `QueryFragment` objects (SQLAlchemy `Select`-based, no string concatenation). See `docs/architecture/cubes.md`.
- **Documentation:** when making code changes, always update the corresponding documentation in `docs/`. This includes architecture docs (`docs/architecture/`), development guides (`docs/development/`), and `CLAUDE.md` itself when the project structure, conventions, or workflows change.
