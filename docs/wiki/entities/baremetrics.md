---
title: Baremetrics
description: Closed-source subscription analytics with an action layer — revenue recovery, forecasting, and cancellation insights on top of metrics.
type: entity
tags: [analytics-tool, competitor, closed-source]
updated: 2026-07-23
---

# Baremetrics

> The most action-oriented tool in the analytics category: metrics plus dunning,
> forecasting, and cancellation insight.

---

## What it is

Baremetrics started where [ChartMogul](chartmogul.md) did — a Stripe dashboard — and
diverged toward *acting* on subscription data rather than only describing it. Recover
handles failed-payment dunning, Forecast+ does financial forecasting against accounting
actuals, and Trial/Cancellation Insights explain funnel behaviour.

## Key facts

| | |
|---|---|
| Category | Analytics layer + action layer |
| Licence | Proprietary SaaS |
| Metrics | 28+ |
| Pricing *(as of March 2026)* | From $108/mo, scaling with MRR tracked (~$358/mo at $100K MRR); Recover and Forecast+ priced separately |
| Free tier | None |
| Billing sources | Stripe, Braintree, Recurly, [Chargebee](chargebee.md), Apple App Store, Google Play, Shopify Partners, custom API |
| Accounting | [QuickBooks Online](quickbooks-online.md), Xero (for Forecast+ actuals) |

## Strengths

- Most complete feature set: analytics + recovery + forecasting + insights
- Revenue recovery has directly measurable ROI
- Forecasting grounded in accounting actuals, not just trend extrapolation
- Industry benchmarking for context

## Limitations

- Most expensive option in the category, especially with add-ons
- No free tier — a barrier for early-stage companies
- Segmentation is basic next to ChartMogul (pre-built segments, monthly cohorts)
- Closed source — metric calculations are not auditable

## Relevance to Tidemill

Baremetrics defines a boundary Tidemill deliberately does not cross. Revenue recovery and
dunning are [explicit non-goals](../../architecture/overview.md) — they are billing-engine
territory and a different competency. Tidemill competes on the transparency and
customisability of the metric layer underneath, not on the action layer above it.

The one place the two overlap conceptually is accounting integration: Baremetrics pulls
QuickBooks/Xero actuals for forecasting, while Tidemill pulls
[QuickBooks Online](quickbooks-online.md) for
[expense analytics](../../architecture/expenses.md). Same source, different purpose.

## Related

- [ChartMogul](chartmogul.md) — the analytics-depth competitor
- [ProfitWell](profitwell.md) — bundles dunning as a paid add-on too
- [Involuntary churn](../concepts/churn.md) — what Recover addresses
- [Trial Conversion](../concepts/trial-conversion.md) — Trial Insights' subject

## Sources

- [Baremetrics Pricing](https://baremetrics.com/pricing)
- [Baremetrics vs ChartMogul vs ProfitWell](https://baremetrics.com/blog/baremetrics-vs-chartmogul-vs-profitwell)
- [Analytics Tools research](../../research/analytics-tools.md)
