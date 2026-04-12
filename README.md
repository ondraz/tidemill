# Tidemill

Open-source subscription analytics engine — transparent, auditable metric computation (MRR, Churn, Retention, LTV, Trials) from any billing system.

Stripe is the primary integration. Lago and Kill Bill are supported as secondary connectors via same-database mode.

**Docs:** https://ondraz.github.io/tidemill/

## Metrics

| Metric | Status | Description |
|--------|--------|-------------|
| **MRR** | Implemented | Monthly Recurring Revenue, ARR, net new MRR breakdown, waterfall |
| **Churn** | Implemented | Logo churn rate, revenue churn rate |
| **Retention** | Implemented | Cohort retention matrix, NRR, GRR |
| **LTV** | Implemented | Lifetime Value (ARPU / churn), ARPU, cohort LTV |
| **Trials** | Implemented | Trial conversion rate, funnel, monthly series |

Every metric is a self-contained class — own tables, event handlers, query methods, and API routes. Adding a metric requires zero changes to existing code.

## Architecture

Two integration modes, chosen per billing source:

1. **Ingestion mode** (Stripe) — webhooks translated to internal events via Kafka, stored in analytics-owned PostgreSQL. Primary integration path.
2. **Same-database mode** (Lago, Kill Bill) — queries the billing engine's PostgreSQL directly. Zero ETL, zero Kafka.

```
Stripe webhooks → Connector → Kafka → Metric handlers → PostgreSQL
                                                              ↑
                                        FastAPI / CLI → MetricsEngine
```

All metric SQL is built through composable query fragments and semantic Cube models — no string concatenation. Dimensional analysis (group by plan, country, currency) works across all metrics via `QuerySpec`.

## Quick Start

```bash
export STRIPE_API_KEY=sk_test_...

# Seed test data (self-contained — starts stack, seeds, validates, stops)
make seed

# Start dev infrastructure (PostgreSQL + Redpanda + stripe listen)
make dev

# Start the API server (separate terminal)
TIDEMILL_DATABASE_URL=postgresql+asyncpg://tidemill:test@localhost:5432/tidemill \
KAFKA_BOOTSTRAP_SERVERS=localhost:9092 \
uv run uvicorn tidemill.api.app:app --port 8000 --reload
```

## API

```bash
# MRR
curl localhost:8000/api/metrics/mrr
curl "localhost:8000/api/metrics/mrr/waterfall?start=2025-09-01&end=2026-03-31"

# Churn
curl "localhost:8000/api/metrics/churn?start=2025-10-01&end=2025-11-01&type=logo"

# Retention
curl "localhost:8000/api/metrics/retention?start=2025-09-01&end=2026-03-31"
curl "localhost:8000/api/metrics/retention?start=2025-10-01&end=2025-11-01&query_type=nrr"

# LTV
curl "localhost:8000/api/metrics/ltv?start=2025-09-01&end=2026-03-31"
curl localhost:8000/api/metrics/ltv/arpu

# Trials
curl "localhost:8000/api/metrics/trials?start=2025-09-01&end=2026-03-31"
curl "localhost:8000/api/metrics/trials/funnel?start=2025-09-01&end=2026-03-31"
```

All endpoints support dimensional analysis via query parameters:

```bash
# MRR by plan interval
curl "localhost:8000/api/metrics/mrr?dimensions=plan_interval"

# MRR filtered by country
curl "localhost:8000/api/metrics/mrr?filter=customer_country=US"
```

## Package Structure

```
tidemill/
├── engine.py                # MetricsEngine — routes queries to metrics
├── models.py                # SQLAlchemy Core tables (billing entities)
├── events.py                # Internal event schema
├── bus.py                   # Kafka producer/consumer
├── state.py                 # Core consumer: events → base tables
├── fx.py                    # Foreign exchange rate conversion
├── connectors/
│   ├── base.py              # WebhookConnector + DatabaseConnector ABCs
│   ├── stripe.py            # Stripe webhook translator
│   ├── lago.py              # Lago database connector
│   └── killbill.py          # Kill Bill database connector
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
└── api/
    └── app.py               # FastAPI application
```

Each metric module follows the same structure: `tables.py` (schema), `cubes.py` (query model), `metric.py` (logic), `routes.py` (API).

## Development

```bash
make install-dev             # Install dev deps + pre-commit hooks
make check                   # Lint + test + typecheck
make test                    # Unit tests only
make check-integration       # Integration tests (starts PostgreSQL)
make docs                    # MkDocs dev server on :8001
```

## Research

- [Market Overview](docs/research/market-overview.md)
- [Business Models](docs/research/business-models.md)
- [Pricing & Billing](docs/research/pricing-and-billing.md)
- [Billing Engines](docs/research/billing-engines.md)
- [Analytics Tools](docs/research/analytics-tools.md)
- [Competitive Matrix](docs/research/competitive-matrix.md)
- [Product Positioning](docs/research/product-positioning.md)

## License

MIT
