---
title: Chargebee
description: Proprietary subscription billing platform; Tidemill's second implemented webhook revenue connector and the proof that ingestion mode generalises.
type: entity
tags: [billing-engine, data-source, closed-source, implemented]
updated: 2026-10-25
---

# Chargebee

> The second revenue source Tidemill ingests — and the reason the canonical vocabulary
> exists.

---

## What it is

A proprietary subscription billing and revenue management platform, widely supported as a
data source across the analytics category — [ChartMogul](chartmogul.md),
[Baremetrics](baremetrics.md), [ProfitWell](profitwell.md) and [SaaSGrid](saasgrid.md) all
connect to it. Its data model differs from [Stripe](stripe-billing.md)'s in vocabulary more
than in shape: item prices, period units, and its own subscription and invoice state
machines.

## Key facts

| | |
|---|---|
| Category | Billing layer (managed) |
| Licence | Proprietary SaaS |
| Deployment | Cloud only |
| Data access | API + webhooks |
| Tidemill integration | `WebhookConnector`, registered as `chargebee` |
| Status | **Implemented** and enabled in production |

## Recent API changes

From the [chargebee-python changelog](../sources/2026-10-25-chargebee-python-changelog.md)
*(February–September 2026)*. Everything that touches subscriptions and invoices was
additive, so the webhook connector needed no change.

| Change | Analytics significance |
|---|---|
| `Subscription.decommissioned` (Feb 2026) and a matching list/export filter (Jul 2026) | Could mark subscriptions to exclude from metrics. Semantics not yet documented in the wiki, and the connector does not read it |
| `exchange_rates` on `Invoice` / `CreditNote` (Jul 2026) | Chargebee's own FX at invoice time, an alternative to Tidemill's daily-rate [FX conversion](../../architecture/database.md). Not used |
| Omnichannel (app-store) subscriptions expanded (Jun–Sep 2026) | A separate resource and event family (`omnichannel_subscription_*`). Not ingested, so app-store revenue billed through Chargebee is invisible to Tidemill |
| Credits ledger: `GrantBlock`, `LedgerAccountBalance` (Jul–Aug 2026) | Prepaid-credit models. Relevant to [usage-based pricing](../concepts/usage-based-pricing.md), not ingested |

## Relevance to Tidemill

Chargebee is implemented today (`tidemill/connectors/chargebee/`) as a
`WebhookConnector`, making it Tidemill's second live revenue source alongside
[Stripe](stripe-billing.md).

Its real significance is architectural. Supporting a second billing vocabulary is what
forced Tidemill's [canonical vocabulary](../../architecture/canonical-vocabulary.md) to
become explicit — the provider-agnostic enums that every connector maps onto:

| Canonical concept | Stripe | Chargebee |
|---|---|---|
| Plan interval | `recurring.interval` | `item_price.period_unit` |
| Pricing model | `billing_scheme` / `recurring.usage_type` | `item_price.pricing_model` |
| Subscription status | `status` | `Subscription.status` |
| Invoice status | `status` | `Invoice.status` |

Edge cases like Chargebee's `non_renewing` — active for the current period but not
renewing — are exactly what the canonical
[pending cancellation](../../architecture/canonical-vocabulary.md) flag was introduced to
represent without losing information.

Running two sources concurrently is also why `source` exists as a dimension on every
subscription cube, so metrics can be grouped or filtered by connector. See
[cubes](../../architecture/cubes.md) and [reports](../../architecture/reports.md).

!!! note "Documentation gap"
    [connectors.md](../../architecture/connectors.md) documents Stripe, Lago, Kill Bill and
    QuickBooks, but has no Chargebee section despite the connector being implemented and
    enabled in production. Recorded in the [wiki log](../log.md) on 2026-07-23.

## Related

- [Stripe Billing](stripe-billing.md) — the reference webhook connector
- [Lago](lago.md), [Kill Bill](kill-bill.md) — same-database alternatives
- [Tidemill](tidemill.md)

## Sources

- [Canonical vocabulary](../../architecture/canonical-vocabulary.md) — enum mappings
- [Connectors](../../architecture/connectors.md) — connector patterns
- [chargebee-python changelog, v3.18 → v3.29](../sources/2026-10-25-chargebee-python-changelog.md) *(captured October 2026)*
