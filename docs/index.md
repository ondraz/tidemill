<p align="center">
  <img src="assets/logo-color.svg" alt="Tidemill" width="280">
</p>

<p align="center">Open-source subscription analytics — compute and visualize MRR, ARR, LTV, retention, churn, and more from your billing data.</p>

## Wiki

A compounding knowledge base — entity and concept pages maintained by an LLM agent as new
sources arrive, rather than documents re-read on every question.

- [How It Works](wiki/how-it-works.md) — the three-layer pattern: raw sources, wiki, schema
- [Catalog](wiki/index.md) — every page with a one-line summary
- [Log](wiki/log.md) — chronological record of ingests, queries, and lint passes

Start with the catalog. Highlights: [Metric Transparency](wiki/concepts/metric-transparency.md)
(the project's core thesis), [MRR](wiki/concepts/mrr.md), and the competitor pages for
[ChartMogul](wiki/entities/chartmogul.md) and [Baremetrics](wiki/entities/baremetrics.md).

## Architecture

Implementation plan for the analytics engine.

- [Overview](architecture/overview.md) — event-driven system design with Kafka
- [Events](architecture/events.md) — internal event schema and Kafka topics
- [Database](architecture/database.md) — PostgreSQL schema, ER diagram, and rationale
- [Connectors](architecture/connectors.md) — webhook translators for Stripe, Lago, Kill Bill
- [Metrics](architecture/metrics.md) — metric plugin system with self-managed tables
- [API](architecture/api.md) — FastAPI endpoints
- [Development](development/development.md) - Local development
- [Deployment](development/deployment.md) — Docker Compose on Hetzner, path to Kubernetes
- [Testing](development/testing.md) — Stripe Test Clocks, seed scripts, webhook forwarding

## Research

Background research and competitive analysis that informed the product direction.

### Market & Models

- [Market Overview](research/market-overview.md) — subscription economy sizing, trends, and key metrics
- [Business Models](research/business-models.md) — subscription model types and where they fit

### Pricing & Billing

- [Pricing & Billing Strategies](research/pricing-and-billing.md) — pricing models, billing mechanics, and optimization
- [Billing Engines](research/billing-engines.md) — comparing Stripe Billing, Lago, and Kill Bill

### Competitive Landscape

- [Analytics Tools](research/analytics-tools.md) — ChartMogul, Baremetrics, ProfitWell, and SaaSGrid
- [Competitive Matrix](research/competitive-matrix.md) — side-by-side feature comparison and gap analysis

### Product

- [Product Positioning](research/product-positioning.md) — where this project fits and why it should exist
