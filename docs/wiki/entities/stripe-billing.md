---
title: Stripe Billing
description: The dominant managed SaaS billing platform and Tidemill's primary revenue integration — the reference implementation for ingestion mode.
type: entity
tags: [billing-engine, data-source, closed-source, implemented]
updated: 2026-10-25
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
| Usage metering | Meter events in, aggregates out — see below |
| Current API version *(as of October 2026)* | `2026-09-30.endive` |
| Data access | API + webhooks |
| Failed-payment recovery | Smart retries, ~41% of failed invoices recovered via ML |

!!! warning "Contradiction"
    Until this update the wiki, following [Billing Engines](../../research/billing-engines.md)
    *(March 2026)*, called Stripe metering "pre-aggregated only — not event-based". The
    [stripe-python 16.0.0 sdist](../sources/2026-10-25-stripe-python-changelog.md) shows
    event-level ingestion through Billing Meters (`MeterEvent`, `MeterEventAdjustment`)
    and no legacy `UsageRecord` resource. Tidemill's own seed creates a Billing Meter. Read
    back, though, usage is only available as `MeterEventSummary`, "an aggregated view …
    within a specified timeframe". *Inference:* the research claim holds for what an
    analytics reader can see and is wrong about how usage enters Stripe. Not yet
    reconciled in `research/billing-engines.md` or `research/competitive-matrix.md`.

## API version history

Stripe ships two named major API versions a year. Each one can break payload shapes,
so connectors must read both the old and new location of any field that moved. Fields
Tidemill reads are listed in [connectors](../../architecture/connectors.md#api-versions).

| Version | Date | What matters for analytics |
|---|---|---|
| `basil` | 2025-03-31 | Subscription period moved onto items; invoice lines nest price and subscription under `pricing` / `parent`; legacy usage records removed in favour of Billing Meters |
| `dahlia` | 2026-03-25 | Additive through the line: `billed_until` and `billing_schedules`, `amount_paid_off_stripe` on invoices, custom cancellation `feedback_option`, many new local payment methods |
| `endive` | 2026-09-30 | **On-demand subscription pause/resume**, with `status_details.paused` giving the reason; item-level trials (`current_trial`); `invoice.status_details.uncollectible.reason`; `payment_method_types` removed from PaymentIntent and Checkout request params |

Source: [stripe-python changelog](../sources/2026-10-25-stripe-python-changelog.md).
`clover` (2025-09-30) sits between basil and dahlia and has not been captured.

## Strengths

- Best API documentation and developer experience in the category
- Strong webhook infrastructure, well suited to real-time event streaming
- Payments and billing in one platform
- Massive integration ecosystem

## Limitations

- Percentage-of-revenue pricing scales poorly for high-volume businesses
- Usage metering exposes only aggregates to readers, limiting usage analytics
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

Stripe exposes usage to readers only in aggregated form (see the contradiction note above),
which is why Tidemill computes the usage component of MRR as a trailing 3-month average of
finalized invoice lines rather than reading a metering stream. [Lago](lago.md) does not have that
limitation, which is part of its analytical appeal. See [MRR](../concepts/mrr.md) and
[Usage-Based Pricing](../concepts/usage-based-pricing.md).

Endive's on-demand pause changed how the connector reads `paused` → `active`. Before
Endive, `paused` arose only when a trial ended without a payment method, so leaving it was
a first activation. Now the connector reads `status_details.paused` and emits
`subscription.resumed` for a pause that followed paid service. The MRR metric books that as
a reactivation, as [definitions](../../definitions.md#mrr-movements) requires. See
[Churn](../concepts/churn.md) for why pauses count as churn at all.

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
- [stripe-python changelog, v15 → v16](../sources/2026-10-25-stripe-python-changelog.md) *(captured October 2026)*
