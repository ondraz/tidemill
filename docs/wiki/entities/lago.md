---
title: Lago
description: Open-source, event-based billing platform for usage-based and hybrid pricing; Tidemill's strongest community alignment and a planned same-database connector.
type: entity
tags: [billing-engine, data-source, open-source, planned]
updated: 2026-07-23
---

# Lago

> Open-source billing built around usage events rather than pre-aggregated totals —
> the natural philosophical partner for open-source analytics.

---

## What it is

A YC-backed open-source billing platform focused on usage-based and hybrid pricing.
You define billable metrics (`api_calls`, `messages_sent`, `storage_gb`) and stream usage
events; Lago aggregates them into invoices from plan definitions. Built on Ruby on Rails,
PostgreSQL, Redis and Sidekiq. Notable users include PayPal, Synthesia and Mistral.ai.

## Key facts

| | |
|---|---|
| Category | Billing layer (open core) |
| Licence | Apache 2.0 core; premium features gated behind Cloud |
| Deployment | Self-hosted (free) or Lago Cloud |
| Usage metering | Event-based, up to ~15,000 events/sec |
| Aggregations | count, sum, max, unique count |
| Data access | **Direct database** + API + webhooks |
| Payment processors | Agnostic — Stripe, GoCardless, Adyen, custom |
| Compliance | SOC 2 Type 2 |
| Adoption *(as of March 2026)* | 7K+ GitHub stars |

## Strengths

- Open-source core with direct database access
- Event-based architecture preserves granular usage data
- Payment-processor agnostic — no Stripe lock-in
- No percentage-of-revenue pricing

## Limitations

- Younger than [Stripe](stripe-billing.md) and [Kill Bill](kill-bill.md); less battle-tested at extreme scale
- Self-hosting requires DevOps capability
- Some advanced features gated behind paid Cloud
- Documentation still maturing

## Relevance to Tidemill

Lago is Tidemill's **beachhead market** and the strongest argument for the project's
existence: Lago users have no dedicated open-source analytics companion today, and are
already philosophically aligned. See
[product positioning](../../research/product-positioning.md).

Technically it is the motivating case for Tidemill's **same-database mode** — analytics
queries Lago's PostgreSQL directly, with zero ETL and no Kafka. That is a fundamentally
different integration shape from the [Stripe](stripe-billing.md) ingestion path, and the
reason `DatabaseConnector` exists alongside `WebhookConnector` in
[connectors](../../architecture/connectors.md).

Because raw usage events are available rather than pre-aggregated totals, Lago can in
principle support more exact [usage revenue](../concepts/usage-based-pricing.md) than
Stripe's trailing-average approximation.

**Status: P1, not yet implemented.** `tidemill/connectors/lago.py` is planned; only
[Stripe](stripe-billing.md) and [Chargebee](chargebee.md) ship today.

## Related

- [Kill Bill](kill-bill.md) — the other open-source billing engine
- [Stripe Billing](stripe-billing.md) — contrasting integration mode
- [Usage-Based Pricing](../concepts/usage-based-pricing.md)

## Sources

- [Lago — Open Source Billing Infrastructure](https://getlago.com/)
- [Lago GitHub Repository](https://github.com/getlago/lago)
- [Lago vs Stripe](https://www.getlago.com/resources/compare/lago-vs-stripe)
- [Billing Engines research](../../research/billing-engines.md)
