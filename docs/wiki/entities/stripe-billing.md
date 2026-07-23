---
title: Stripe Billing
description: The dominant managed SaaS billing platform and Tidemill's primary revenue integration — the reference implementation for ingestion mode.
type: entity
tags: [billing-engine, data-source, closed-source, implemented]
updated: 2026-07-23
---

# Stripe Billing

> The largest installed base in subscription billing, and Tidemill's reference
> connector implementation.

---

## What it is

A fully managed, cloud-only billing platform inside the broader Stripe payments
ecosystem. Its data model centres on Customers, Subscriptions, Invoices and Payment
Intents, exposed through REST APIs and an extensive webhook catalogue. Most subscription
analytics tools — [ChartMogul](chartmogul.md), [Baremetrics](baremetrics.md),
[ProfitWell](profitwell.md) — began life as Stripe data readers.

## Key facts

| | |
|---|---|
| Category | Billing layer (managed) |
| Licence | Proprietary SaaS |
| Deployment | Cloud only |
| Pricing *(as of March 2026)* | 0.7% of billing volume, on- and off-Stripe; invoicing extra |
| Usage metering | Pre-aggregated only — not event-based |
| Data access | API + webhooks |
| Failed-payment recovery | Smart retries, ~41% of failed invoices recovered via ML |

## Strengths

- Best API documentation and developer experience in the category
- Strong webhook infrastructure, well suited to real-time event streaming
- Payments and billing in one platform
- Massive integration ecosystem

## Limitations

- Percentage-of-revenue pricing scales poorly for high-volume businesses
- Usage metering requires pre-aggregation, limiting complex metering
- No self-hosting — data lives on Stripe's infrastructure
- Awkward for yearly plans with monthly overages, multi-currency consolidation, and
  complex proration

## Relevance to Tidemill

Stripe is Tidemill's **P0 revenue connector and the reference implementation** for
[ingestion mode](../../architecture/overview.md): webhooks are translated into internal
events, published to Kafka, and materialised into analytics-owned PostgreSQL. Every later
connector — including [Chargebee](chargebee.md) — was built against the pattern Stripe
established. See [connectors](../../architecture/connectors.md) and
[events](../../architecture/events.md).

Stripe's pre-aggregation constraint is the reason Tidemill computes the usage component
of MRR as a trailing 3-month average rather than reading a metering stream: the granular
events simply are not available on this source. [Lago](lago.md) does not have that
limitation, which is part of its analytical appeal. See [MRR](../concepts/mrr.md) and
[Usage-Based Pricing](../concepts/usage-based-pricing.md).

Stripe Test Clocks drive the seed data used for local development and metric verification
— see [testing](../../development/testing.md).

## Related

- [Lago](lago.md), [Kill Bill](kill-bill.md) — open-source alternatives
- [Chargebee](chargebee.md) — second implemented webhook source
- [MRR](../concepts/mrr.md), [Usage-Based Pricing](../concepts/usage-based-pricing.md)

## Sources

- [Stripe Billing Pricing](https://stripe.com/billing/pricing)
- [Stripe usage-based pricing plans](https://docs.stripe.com/billing/subscriptions/usage-based/pricing-plans)
- [Billing Engines research](../../research/billing-engines.md)
