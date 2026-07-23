---
title: ChartMogul
description: Closed-source subscription analytics platform; the depth leader in segmentation and cohort analysis, and Tidemill's closest functional competitor.
type: entity
tags: [analytics-tool, competitor, closed-source]
updated: 2026-07-23
---

# ChartMogul

> Subscription analytics platform positioning as a subscription *data platform* rather
> than a dashboard. The closest competitor to Tidemill in analytical ambition.

---

## What it is

ChartMogul sits downstream of a billing engine, ingests subscriptions, invoices and
payments, and computes SaaS metrics on top. It leans harder on data modelling than its
competitors — custom dimensions, enrichment, and a built-in CRM — which makes it the
depth leader for [segmentation](../../architecture/segments.md) and
[cohort retention](../concepts/cohort-retention.md).

## Key facts

| | |
|---|---|
| Category | Analytics layer (reads billing data, computes metrics) |
| Licence | Proprietary SaaS |
| Metrics | 26+ |
| Pricing *(as of March 2026)* | Free under $10K MRR; Scale from $100/mo per additional $10K MRR tracked; CRM seats $39/mo |
| Billing sources | Stripe, Braintree, Recurly, [Chargebee](chargebee.md), PayPal, GoCardless, Zuora, Chargify, Apple App Store, Google Play, custom API |
| Open-source billing support | None ([Lago](lago.md), [Kill Bill](kill-bill.md) unsupported) |

## Strengths

- Deepest segmentation and cohort analysis in the category
- Broadest set of native billing connectors (10+)
- Data-platform approach allows analysis beyond pre-built dashboards
- Free tier for early-stage companies

## Limitations

- Closed source — metric calculations are not auditable
- No revenue recovery / dunning; pure analytics with no action layer
- Pricing scales with MRR tracked, which compounds badly at scale
- Limited export and data-warehouse connectivity

## Relevance to Tidemill

ChartMogul is the benchmark Tidemill measures its metric definitions against.
[`definitions.md`](../../definitions.md) documents every place Tidemill deliberately
diverges — same-period joiners in logo churn, gross vs. net revenue churn, reactivation
in Quick Ratio, trailing-average LTV. Those divergences are stated precisely *because*
ChartMogul cannot state its own: that contrast is the
[metric transparency](../concepts/metric-transparency.md) argument in concrete form.

Differentiation is philosophical rather than feature-count: auditable computation,
self-hosting, and native open-source billing support.

## Related

- [Baremetrics](baremetrics.md) — the action-oriented competitor
- [ProfitWell](profitwell.md) — the free competitor
- [Tidemill](tidemill.md) — this project
- [Metric Transparency](../concepts/metric-transparency.md)

## Sources

- [ChartMogul Pricing](https://chartmogul.com/pricing/)
- [ChartMogul Subscription Analytics](https://chartmogul.com/subscription-analytics/)
- [Analytics Tools research](../../research/analytics-tools.md)
