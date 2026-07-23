---
title: Catalog
description: Every page in the wiki with a one-line summary, grouped by category.
type: meta
updated: 2026-07-23
---

# Catalog

> The content index for the wiki. Every page, one line each. Start here when answering a
> question, then drill into the pages that look relevant.
>
> New to this? Read [how it works](how-it-works.md) first. For the chronological view of
> what changed and when, see the [log](log.md).

---

## Entities

Companies, products, and systems. One page each.

### This project

| Page | Summary |
|---|---|
| [Tidemill](entities/tidemill.md) | Open-source subscription analytics engine offering transparent, auditable metric computation for any billing system. |

### Analytics tools (competitors)

| Page | Summary |
|---|---|
| [ChartMogul](entities/chartmogul.md) | Depth leader in segmentation and cohort analysis; Tidemill's closest functional competitor. |
| [Baremetrics](entities/baremetrics.md) | Analytics plus an action layer — revenue recovery, forecasting, cancellation insight. |
| [ProfitWell](entities/profitwell.md) | Free metrics owned by Paddle; hardest competitor to undercut on price. |
| [SaaSGrid](entities/saasgrid.md) | Finance-oriented revenue intelligence with 150+ metrics, aimed at CFOs. |

### Billing engines (revenue sources)

| Page | Summary |
|---|---|
| [Stripe Billing](entities/stripe-billing.md) | Dominant managed billing platform; Tidemill's reference connector. **Implemented.** |
| [Chargebee](entities/chargebee.md) | Second implemented webhook source; the reason the canonical vocabulary exists. **Implemented.** |
| [Lago](entities/lago.md) | Open-source event-based billing for usage models; the beachhead market. *Planned (P1).* |
| [Kill Bill](entities/kill-bill.md) | Veteran fully open-source, plugin-driven billing platform. *Planned (P1).* |

### Accounting (expense sources)

| Page | Summary |
|---|---|
| [QuickBooks Online](entities/quickbooks-online.md) | First expense-side integration; makes cost analysis possible alongside revenue. **Implemented.** |

---

## Concepts

Domain ideas that recur across sources. Each page explains the idea, why it matters, how
Tidemill computes it, and where the definitions are contested.

| Page | Summary |
|---|---|
| [MRR](concepts/mrr.md) | Normalized monthly revenue from active subscriptions; the base every other metric derives from. |
| [Churn](concepts/churn.md) | Customers or revenue lost in a period, and the choices that make the number contestable. |
| [Net Revenue Retention](concepts/net-revenue-retention.md) | Whether the existing customer base grows revenue on its own — NRR and its gross counterpart GRR. |
| [Cohort Retention](concepts/cohort-retention.md) | What fraction of customers who started together are still active N months later. |
| [LTV](concepts/ltv.md) | Expected total revenue from a customer before churn; the most assumption-laden metric in the category. |
| [Usage-Based Pricing](concepts/usage-based-pricing.md) | Charging for consumption — the dominant emerging pattern and the biggest source of analytics complexity. |
| [Trial Conversion](concepts/trial-conversion.md) | Share of trials that become paying customers, and why historical values legitimately move. |
| [Metric Transparency](concepts/metric-transparency.md) | The thesis that metrics should be auditable — the idea Tidemill's positioning rests on. |

---

## Synthesis

Longer-form analysis that argues a position by linking out to entity and concept pages.
These live in the [Research](../research/market-overview.md) section.

| Page | Summary |
|---|---|
| [Market Overview](../research/market-overview.md) | Subscription economy sizing, model types, and the metrics every subscription business tracks. |
| [Business Models](../research/business-models.md) | Subscription model types and where each fits. |
| [Pricing & Billing](../research/pricing-and-billing.md) | Pricing models, billing mechanics, and optimization levers. |
| [Billing Engines](../research/billing-engines.md) | Stripe Billing vs. Lago vs. Kill Bill as upstream data sources. |
| [Analytics Tools](../research/analytics-tools.md) | ChartMogul, Baremetrics, ProfitWell, and SaaSGrid compared. |
| [Competitive Matrix](../research/competitive-matrix.md) | Side-by-side feature comparison and gap analysis. |
| [Product Positioning](../research/product-positioning.md) | Where Tidemill fits and why it should exist. |

---

## Reference

Hand-authored specifications. In scope for wiki maintenance and lint passes, but they
describe what Tidemill *does* rather than what the wiki has *learned* — the agent keeps
them consistent and cross-referenced, it does not rewrite them from sources.

| Page | Summary |
|---|---|
| [Definitions](../definitions.md) | Canonical metric formulas, conventions, and documented divergences from ChartMogul. |
| [Architecture — Overview](../architecture/overview.md) | System design, dual integration modes, MVP scope. |
| [Architecture — Events](../architecture/events.md) | Internal event schema and Kafka topics. |
| [Architecture — Database](../architecture/database.md) | PostgreSQL schema and deployment topologies. |
| [Architecture — Connectors](../architecture/connectors.md) | Webhook, database, and expense connector patterns. |
| [Architecture — Canonical Vocabulary](../architecture/canonical-vocabulary.md) | Provider-agnostic enums every connector maps onto. |
| [Architecture — Cubes](../architecture/cubes.md) | Query algebra: cubes and composable query fragments. |
| [Architecture — Metrics](../architecture/metrics.md) | Metric base class and built-in metric implementations. |
| [Architecture — Segments](../architecture/segments.md) | Customer attribute EAV, segment DSL, compare mode. |
| [Architecture — Expenses](../architecture/expenses.md) | Platform-neutral expense model and canonical enums. |
| [Architecture — API](../architecture/api.md) | FastAPI endpoints and CLI interface. |
| [Architecture — Reports](../architecture/reports.md) | Pre-built charts and summaries for every metric. |
| [Development](../development/development.md) | Local development environment setup. |
| [Testing](../development/testing.md) | Test data generation and seed scripts. |
| [Deployment](../development/deployment.md) | Docker Compose and Terraform infrastructure. |

---

## Sources

Raw source material lives in `docs/wiki/sources/`. It is tracked in git so the agent can
re-read it, but excluded from the published site — see
[how it works](how-it-works.md). Conventions and the current capture backlog are in
`docs/wiki/sources/README.md`.
