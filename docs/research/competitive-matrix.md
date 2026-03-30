# Competitive Feature Matrix

> Side-by-side capability comparison across both billing engines and analytics tools, identifying gaps an open-source analytics package can fill.
> Last updated: March 2026

---

## How to Read This Matrix

This matrix maps capabilities across two layers of the subscription stack:

- **Billing Engines** (Stripe, Lago, Kill Bill) — process subscriptions, generate invoices, handle payments
- **Analytics Tools** (ChartMogul, Baremetrics, ProfitWell, SaaSGrid) — read billing data, compute metrics, visualize insights

An open-source analytics package sits in the analytics layer but must integrate tightly with the billing layer. The matrix reveals where existing tools are strong, where they are weak, and where whitespace exists.

Rating scale: **Strong** (market-leading), **Adequate** (functional), **Weak** (limited), **Absent** (not available).

---

## Billing Engine Capabilities

| Capability | Stripe Billing | Lago | Kill Bill |
|---|---|---|---|
| **Subscription Management** | | | |
| Plan creation and management | Strong | Strong | Strong |
| Plan versioning and migration | Adequate | Strong | Strong |
| Per-customer plan overrides | Weak | Strong | Strong |
| Multi-currency | Strong | Strong | Strong |
| **Pricing Model Support** | | | |
| Flat-rate | Strong | Strong | Strong |
| Tiered | Strong | Strong | Strong |
| Per-seat | Strong | Strong | Strong |
| Usage-based metering | Adequate (pre-aggregated) | Strong (event-based) | Strong (plugin-based) |
| Hybrid (base + usage) | Weak | Strong | Strong |
| **Billing Operations** | | | |
| Automated invoicing | Strong | Strong | Strong |
| Proration handling | Strong | Strong | Strong |
| Dunning / retry logic | Strong (ML-powered) | Adequate | Adequate |
| Credit notes and refunds | Strong | Strong | Strong |
| Prepaid credits / wallets | Weak | Strong | Absent |
| **Integration and Access** | | | |
| API quality | Strong | Strong | Adequate |
| Webhook events | Strong | Strong | Adequate |
| Direct database access | Absent | Strong (self-hosted) | Strong (self-hosted) |
| Payment processor flexibility | Stripe only | Multi-processor | Multi-processor |
| **Deployment** | | | |
| Cloud / managed | Strong | Strong | Absent |
| Self-hosted | Absent | Strong | Strong |
| **Data Ownership** | | | |
| Full data portability | Weak | Strong | Strong |
| No vendor lock-in | Weak | Strong | Strong |

---

## Analytics Tool Capabilities

| Capability | ChartMogul | Baremetrics | ProfitWell | SaaSGrid |
|---|---|---|---|---|
| **Core Metrics** | | | | |
| MRR / ARR | Strong | Strong | Strong | Strong |
| Churn (logo and revenue) | Strong | Strong | Strong | Strong |
| LTV calculation | Strong | Strong | Strong | Strong |
| ARPU | Strong | Strong | Strong | Strong |
| Net Revenue Retention | Strong | Adequate | Adequate | Strong |
| Expansion / Contraction MRR | Strong | Strong | Adequate | Strong |
| CAC and LTV:CAC | Weak | Weak | Weak | Strong |
| **Segmentation and Cohorts** | | | | |
| Custom segmentation | Strong | Weak (pre-built) | Weak | Strong |
| Cohort analysis | Strong | Adequate (monthly) | Adequate | Strong |
| Custom dimensions / attributes | Strong | Weak | Weak | Strong |
| **Actionable Features** | | | | |
| Revenue recovery (dunning) | Absent | Strong (Recover) | Strong (Retain) | Absent |
| Forecasting | Weak | Strong (Forecast+) | Absent | Adequate |
| Trial insights | Absent | Strong | Absent | Absent |
| Cancellation insights | Absent | Strong | Absent | Absent |
| Benchmarking | Absent | Strong | Strong (34K+) | Absent |
| **Data and Integration** | | | | |
| Billing source connectors | Strong (10+) | Adequate (8+) | Adequate (6+) | Strong (8+) |
| Open-source billing support | Absent | Absent | Absent | Absent |
| CRM integration | Strong (built-in) | Weak | Adequate | Strong |
| Accounting integration | Absent | Strong (QBO, Xero) | Absent | Strong (NetSuite, QBO, Sage, Xero) |
| Data warehouse export | Weak | Weak | Weak | Adequate |
| API for programmatic access | Adequate | Adequate | Adequate | Adequate |
| **Transparency and Control** | | | | |
| Open-source | Absent | Absent | Absent | Absent |
| Metric calculation transparency | Absent | Absent | Absent | Absent |
| Self-hosted deployment | Absent | Absent | Absent | Absent |
| Custom metric definitions | Weak | Absent | Absent | Adequate |
| **Pricing** | | | | |
| Free tier | Strong (< $10K MRR) | Absent | Strong (unlimited) | Absent |
| Cost at $100K MRR | ~$100/mo | ~$358/mo | Free | ~$5,000/yr |
| Cost at $1M MRR | ~$1,000/mo | ~$700+/mo | Free | Custom |

---

## Gap Analysis: Where No Existing Tool Is Strong

The matrix reveals several clear gaps that represent opportunity for an open-source analytics package:

### Gap 1: Metric Calculation Transparency
No existing analytics tool lets users inspect, audit, or customize how metrics are computed. Every tool is a black box. For companies with complex billing (usage-based, hybrid, multi-currency), this is a real pain point — generic MRR or churn formulas may not match their business reality. An open-source tool with transparent, documented metric calculations addresses this directly.

### Gap 2: Open-Source Billing Engine Integration
No analytics tool offers first-class integration with Lago or Kill Bill. This is a significant blind spot given the growing adoption of open-source billing. Companies choosing Lago or Kill Bill for billing have zero dedicated analytics options — they must build custom dashboards or try to shoehorn data into tools designed for Stripe.

### Gap 3: Self-Hosted Deployment
No analytics tool can be self-hosted. Companies in regulated industries (healthcare, finance, government) or with strict data residency requirements cannot use any existing subscription analytics tool without sending billing data to a third party. Self-hosted analytics paired with self-hosted billing (Lago or Kill Bill) is a complete stack that doesn't exist today.

### Gap 4: Data Warehouse Native
Existing tools are designed as standalone SaaS applications with their own data stores. None are designed to work natively with a company's existing data warehouse (Snowflake, BigQuery, PostgreSQL). An analytics package that computes metrics directly on warehouse data, or exports cleanly to warehouses, would serve the growing "modern data stack" community.

### Gap 5: Customizable Metric Definitions
Every tool defines MRR, churn, and LTV with fixed formulas. But these metrics are not standardized — different companies legitimately need different calculation methods. For example, should annual subscriptions be recognized as MRR monthly or at time of payment? How should free trials be counted? How should multi-product subscriptions be attributed? An open-source tool can offer pluggable metric definitions that users configure for their specific business logic.

---

## Landscape Positioning Map

```
                    ANALYTICS DEPTH
                         High
                          |
                 SaaSGrid |  ChartMogul
                    ($$$)  |  ($$)
                          |
   ACTION-              --+--              DATA
   ORIENTED               |               PLATFORM
                          |
              Baremetrics |
                   ($$)   |
                          |  ProfitWell
                          |  (Free)
                          |
                         Low

   ─────────────────────────────────────────
   Closed Source          |          Open Source
                          |
                     [WHITESPACE]
                   Open-source analytics
                   Self-hosted, transparent
                   Lago + Kill Bill native
```

The whitespace is clear: no tool combines analytical depth with open-source transparency. ProfitWell compressed the market on price (free), but an open-source tool competes on a different dimension entirely — transparency, customizability, and data ownership.

---

## Sources

Cross-references [Billing Engines](./billing-engines.md) and [Analytics Tools](./analytics-tools.md) for detailed per-product analysis.
