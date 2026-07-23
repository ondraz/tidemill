---
title: Kill Bill
description: The veteran fully open-source billing platform — plugin-driven, enterprise-grade, and a planned same-database connector for Tidemill.
type: entity
tags: [billing-engine, data-source, open-source, planned]
updated: 2026-07-23
---

# Kill Bill

> A decade of production billing under Apache 2.0, with no gated features and
> everything pluggable.

---

## What it is

A Java-based, plugin-driven billing platform maintained for over ten years. Every
component — tax engine, invoice formatter, payment gateway, usage calculator — can be
swapped via plugins. Data lives in a relational database (MySQL or PostgreSQL) that the
operator controls. Its catalog system handles add-ons, billing alignment and proration for
genuinely complex enterprise scenarios.

## Key facts

| | |
|---|---|
| Category | Billing layer (fully open source) |
| Licence | Apache 2.0 — no paid tiers, no feature gating |
| Language | Java (plugin/OSGi architecture) |
| Deployment | Self-hosted or cloud |
| Usage metering | Plugin-based |
| Data access | **Direct database** + plugins + API |
| Multi-tenancy | Built in |
| Business model | Consulting and support services |

## Strengths

- Ten years of production use in complex enterprise environments
- Completely free with nothing gated
- Most flexible architecture in the category — everything is pluggable
- No vendor lock-in whatsoever

## Limitations

- Steep learning curve; Java/OSGi knowledge required
- Heavy setup and operational cost
- Documentation is functional but dated
- Smaller community than [Lago](lago.md)'s
- Dated UI/UX

## Relevance to Tidemill

Kill Bill is the **third integration priority** — a smaller but loyal user base whose
billing logic is already heavily customised. That customisation is exactly why these users
need auditable, configurable metric computation: generic formulas are least likely to
match their reality. See [Metric Transparency](../concepts/metric-transparency.md).

Like [Lago](lago.md), it is a **same-database** connector — `DatabaseConnector` rather than
`WebhookConnector` — querying the billing engine's tables directly with no ETL. See
[connectors](../../architecture/connectors.md).

**Status: P1, not yet implemented.** `tidemill/connectors/killbill.py` is planned.

## Related

- [Lago](lago.md) — the other open-source billing engine
- [Stripe Billing](stripe-billing.md) — contrasting integration mode
- [Metric Transparency](../concepts/metric-transparency.md)

## Sources

- [Kill Bill](https://killbill.io/)
- [Kill Bill Overview](https://killbill.io/overview)
- [Kill Bill GitHub Repository](https://github.com/killbill/killbill)
- [Billing Engines research](../../research/billing-engines.md)
