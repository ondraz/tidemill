# Subscription Billing Engines: Competitive Landscape

> Comparing Stripe Billing, Lago, and Kill Bill as the upstream data sources an open-source analytics package would integrate with.
> Last updated: March 2026

---

## Why Billing Engines Matter for Analytics

A subscription analytics tool does not process payments — it reads billing data and computes metrics. The billing engine is the upstream source of truth. Understanding how each engine stores and exposes subscription events, invoices, and customer data determines what an analytics package can compute and how it integrates.

The three most relevant billing engines form a spectrum from fully managed (Stripe) to open-source with cloud option (Lago) to fully self-hosted open-source (Kill Bill).

---

## Stripe Billing

### Overview

Stripe Billing is the dominant SaaS billing platform, part of the broader Stripe payments ecosystem. It is a fully managed, cloud-only service. Most subscription analytics tools (ChartMogul, Baremetrics, ProfitWell) were originally built as Stripe data readers.

### Architecture and Data Model

Stripe Billing uses an API-first, cloud-hosted architecture. Subscription data flows through well-documented REST APIs and webhooks. The data model centers on Customers, Subscriptions, Invoices, and Payment Intents. Stripe is not event-based for usage billing — you must pre-aggregate usage events into proper units before sending them to Stripe, which limits flexibility for complex metering.

### Key Capabilities

- Supports flat-rate, tiered, per-seat, and usage-based pricing models
- Automated invoicing with customizable templates
- Customer portal for self-service subscription management
- Smart retry logic for failed payments (recovers ~41% of failed invoices via ML)
- Revenue recognition support (Stripe Revenue Recognition add-on)
- Extensive webhook events for real-time data streaming

### Pricing

0.7% of billing volume (both on- and off-Stripe). Additional charges for Stripe Invoicing (~$0.50/invoice on Starter). This percentage-of-revenue model becomes expensive at scale.

### Data Access for Analytics

Stripe provides rich webhook events and API endpoints that make it straightforward to build analytics on top of. Most existing analytics tools started here because Stripe's data model is well-structured and the API is excellent. However, Stripe's data model has limitations for complex billing scenarios (yearly plans with monthly overages, multi-currency consolidation, complex proration).

### Strengths

- Best API documentation and developer experience in the category
- Massive ecosystem of integrations and tools built on top
- Handles payment processing + billing in one platform
- Strong webhook infrastructure for real-time event streaming

### Weaknesses

- Percentage-of-revenue pricing scales poorly for high-volume businesses
- Not event-based for usage metering — requires pre-aggregation
- Vendor lock-in — migrating off Stripe is painful
- Limited flexibility for complex billing scenarios
- No self-hosting option — data lives on Stripe's infrastructure

---

## Lago

### Overview

Lago is an open-source billing platform focused on usage-based and hybrid pricing models. YC-backed, with notable customers including PayPal, Synthesia, and Mistral.ai. Available as self-hosted (free) or Lago Cloud (managed).

### Architecture and Data Model

Lago uses an event-based architecture that can ingest up to 15,000 billing events per second. You define custom billable metrics (api_calls, messages_sent, storage_gb) and send usage events via API. Lago aggregates these events into invoices based on plan definitions. Built with Ruby on Rails, PostgreSQL, Redis, and Sidekiq.

### Key Capabilities

- Custom billable metrics with flexible aggregation (count, sum, max, unique count)
- Subscription management with plan overrides per customer
- Prepaid credits and wallet functionality
- Coupons and discount management
- Multi-currency support
- Credit notes and refunds
- Payment-processor agnostic (works with Stripe, GoCardless, Adyen, or custom)
- SOC 2 Type 2 certified

### Pricing

Self-hosted: Free (Apache 2.0 license for core). Lago Cloud: tiered pricing based on usage. Premium features (branded invoices, customer portal, advanced invoicing logic) are gated behind Cloud.

### Data Access for Analytics

Because Lago is open-source and self-hosted, you have direct database access to all billing data. The event-based architecture means raw usage events are available for analytics, not just aggregated invoice data. This is a significant advantage for building detailed analytics. Lago also exposes webhooks and APIs for real-time event streaming.

### Strengths

- Open-source core with direct database access
- Event-based architecture captures granular usage data
- Payment-processor agnostic — not locked into Stripe
- No percentage-of-revenue pricing
- Growing community and active development

### Weaknesses

- Younger than Stripe and Kill Bill — less battle-tested at extreme scale
- Self-hosted deployment requires DevOps expertise
- Some advanced features gated behind paid Cloud offering
- Smaller ecosystem of third-party integrations
- Documentation still maturing compared to Stripe

---

## Kill Bill

### Overview

Kill Bill is the veteran open-source billing platform, actively maintained for over a decade. Fully open-source under Apache 2.0. Java-based, plugin-driven architecture designed for enterprise-grade billing complexity.

### Architecture and Data Model

Kill Bill is Java-based with a highly modular, plugin-driven architecture. Every component (tax engine, invoice formatter, payment gateway, usage calculator) can be swapped via plugins. Data is stored in a relational database (MySQL/PostgreSQL). The catalog system handles complex pricing scenarios including add-ons, multiple payment methods, and billing alignment options.

### Key Capabilities

- Enterprise-grade subscription and pricing catalog
- Plugin system for extensibility (tax, payments, notifications, analytics)
- Multi-tenancy support
- Built-in real-time analytics and financial reports
- Supports complex billing scenarios (add-ons, alignment, proration)
- On-premises or cloud deployment
- No vendor lock-in — you own all data

### Pricing

Completely free and open-source (Apache 2.0). No paid tiers or gated features. Revenue comes from consulting and support services.

### Data Access for Analytics

Kill Bill stores all billing data in a relational database you control. The plugin architecture means you can write custom analytics plugins that hook directly into billing events. Built-in reporting provides basic analytics, but the data is fully accessible for external analytics tools.

### Strengths

- Decade of production use in complex enterprise environments
- Completely free with no feature gating
- Most flexible architecture — everything is pluggable
- Strong multi-tenancy and enterprise features
- No vendor lock-in whatsoever

### Weaknesses

- Steep learning curve — Java/OSGi knowledge required
- Heavy setup and operational costs
- Documentation is functional but not modern
- Smaller community than Lago's growing ecosystem
- UI/UX is dated compared to newer alternatives

---

## Comparison Summary

| Dimension | Stripe Billing | Lago | Kill Bill |
|---|---|---|---|
| License | Proprietary (SaaS) | Apache 2.0 (open core) | Apache 2.0 (fully open) |
| Language | N/A (API only) | Ruby on Rails | Java |
| Deployment | Cloud only | Self-hosted or Cloud | Self-hosted or Cloud |
| Pricing Model | 0.7% of billing volume | Free self-hosted / paid Cloud | Free |
| Usage Metering | Pre-aggregated only | Event-based (15k events/sec) | Plugin-based |
| Data Access | API + Webhooks | Direct DB + API + Webhooks | Direct DB + Plugins + API |
| Setup Complexity | Low | Medium | High |
| Maturity | Very High | Medium (growing fast) | Very High |
| Best For | Teams wanting managed simplicity | Usage-based / hybrid billing | Complex enterprise scenarios |

---

## Implications for an Open-Source Analytics Package

An open-source subscription analytics tool should integrate with all three engines, but prioritize differently:

**Stripe first** — largest installed base by far. Most potential users already have Stripe. Build the Stripe integration as the reference implementation. Leverage Stripe's excellent webhook infrastructure.

**Lago second** — natural philosophical alignment (open-source analytics on open-source billing). Direct database access enables deeper analytics than what's possible through Stripe's API alone. The event-based architecture provides granular usage data that is valuable for analytics.

**Kill Bill third** — smaller but loyal user base with complex billing needs. These users are most likely to need customizable analytics because their billing logic is already highly customized.

The key architectural insight: design the analytics package to work with any billing data source through an adapter pattern. The billing engine provides raw events and invoice data; the analytics package normalizes this into a common data model and computes metrics. This mirrors how ChartMogul works — it supports multiple billing sources through dedicated integrations.

---

## Sources

- [Stripe Billing Pricing](https://stripe.com/billing/pricing)
- [Stripe Billing Documentation](https://docs.stripe.com/billing/subscriptions/usage-based/pricing-plans)
- [Research.com — Stripe Billing Review 2026](https://research.com/software/reviews/stripe-billing)
- [Lago — Open Source Billing Infrastructure](https://getlago.com/)
- [Lago GitHub Repository](https://github.com/getlago/lago)
- [Lago vs Stripe Comparison](https://www.getlago.com/resources/compare/lago-vs-stripe)
- [Kill Bill — Open Source Billing Platform](https://killbill.io/)
- [Kill Bill GitHub Repository](https://github.com/killbill/killbill)
- [Kill Bill Overview](https://killbill.io/overview)
- [Flexprice — Open Source Billing Alternatives 2026](https://flexprice.io/blog/best-open-source-alternatives-to-traditional-billing-platforms)
- [StackShare — Kill Bill vs Stripe Billing](https://stackshare.io/stackups/killbill-vs-stripe-billing)
