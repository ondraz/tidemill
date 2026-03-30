# Subscription Analytics Tools: Competitive Landscape

> Comparing ChartMogul, Baremetrics, ProfitWell (Paddle), and SaaSGrid — the established players an open-source analytics package would compete against.
> Last updated: March 2026

---

## Category Definition

Subscription analytics tools sit downstream of billing engines. They ingest billing data (subscriptions, invoices, payments, cancellations) and compute SaaS metrics: MRR, churn, LTV, cohort retention, expansion revenue, and more. They do not process payments — they read payment data and make it actionable.

The core value proposition is: connect your billing source, get a dashboard of subscription metrics without building it yourself.

---

## ChartMogul

### Overview

ChartMogul is the most analytics-focused tool in the category, with the strongest segmentation and cohort analysis capabilities. It positions as a subscription data platform rather than just a dashboard — emphasizing data enrichment, custom dimensions, and a built-in CRM.

### Key Capabilities

- Subscription analytics with 26+ SaaS metrics (MRR, ARR, churn, LTV, ARPU, etc.)
- Advanced cohort analysis with custom dimensions (plan, geography, acquisition channel)
- Powerful segmentation engine for slicing metrics by any customer attribute
- Built-in CRM with customer profiles, activity timelines, and health scoring
- Data enrichment via Clearbit integration
- Custom attributes and tags for flexible data modeling
- Integrations: Stripe, Braintree, Recurly, Chargebee, PayPal, GoCardless, Zuora, Chargify, Apple App Store, Google Play, plus custom API

### Pricing

Free for companies under $10K MRR (Launch plan). Scale plan starts at $100/month per additional $10K MRR tracked. Volume plan for high-revenue businesses with custom pricing. Each plan includes 1 free CRM Pro seat; additional seats at $39/month.

### Strengths

- Deepest segmentation and cohort analysis in the category
- Broadest billing source integrations (10+ native connectors)
- Data platform approach allows flexible analytics beyond pre-built dashboards
- Free tier for early-stage startups
- Clean, well-designed UI

### Weaknesses

- No revenue recovery / dunning support — pure analytics, no action layer
- No forecasting beyond basic trend extrapolation
- Pricing scales with MRR tracked, which gets expensive at scale
- Closed source — metric calculations are opaque
- Limited export and data warehouse connectivity

---

## Baremetrics

### Overview

Baremetrics is the most action-oriented tool in the category. Beyond analytics dashboards, it includes revenue recovery (Recover), forecasting (Forecast+), and cancellation insights. It positions as a tool that helps you both understand and act on your subscription data.

### Key Capabilities

- 28+ subscription metrics with real-time dashboards
- Baremetrics Recover: automated dunning with pre-failure emails, failed payment sequences, in-app reminders, and paywalls (recovers failed payments that cause involuntary churn)
- Forecast+: financial forecasting integrated with QuickBooks Online and Xero for actuals
- Trial Insights: visibility into trial user behavior and conversion funnels
- Cancellation Insights: understand why customers cancel
- Control Center: high-level executive dashboard for quick decision-making
- Benchmarking against anonymized industry peers
- Integrations: Stripe, Braintree, Recurly, Apple App Store, Google Play, Chargebee, Shopify Partners, plus custom API

### Pricing

Starts at $108/month for smaller businesses, scaling with MRR tracked (e.g., ~$358/month at $100K MRR, ~$700+/month at $1M MRR). Recover and Forecast+ are add-on products with additional pricing.

### Strengths

- Most complete feature set: analytics + recovery + forecasting + insights
- Revenue recovery (Recover) directly impacts bottom line — ROI is measurable
- Financial forecasting with accounting system integration
- Trial and cancellation insights provide actionable context
- Industry benchmarking for context on your metrics

### Weaknesses

- Expensive compared to alternatives, especially with add-ons
- Segmentation is less powerful than ChartMogul (basic monthly cohorts, pre-built segments)
- No free tier — cost is a barrier for early-stage companies
- Closed source — metric calculations are opaque
- UI can feel cluttered with all the feature additions

---

## ProfitWell (Paddle Metrics)

### Overview

ProfitWell was acquired by Paddle in 2022 for $200M. The core metrics product is now called ProfitWell Metrics and is offered free to all Paddle users — and to non-Paddle users as well. ProfitWell's strategy was always to give away analytics for free and monetize through revenue optimization products (Retain for dunning, Recognized for revenue recognition).

### Key Capabilities

- Core SaaS metrics: MRR, churn, LTV, ARPU, cohort analysis, customer segmentation
- Benchmarking against 34,000+ subscription companies
- Free data enrichment to improve segmentation
- Customer health scores and churn risk signals
- ProfitWell Retain: automated revenue recovery (paid product)
- ProfitWell Recognized: revenue recognition automation (paid product)
- Integrations: Stripe, Braintree, Recurly, Chargebee, Zuora, Paddle, plus custom API
- Slack and HubSpot/Intercom/Salesforce integrations for workflow embedding

### Pricing

ProfitWell Metrics: Free forever, no revenue caps, no user limits. Retain and Recognized are paid products with separate pricing (typically performance-based for Retain).

### Strengths

- Free core product — unbeatable price point
- Largest benchmarking dataset (34K+ companies)
- Strong ecosystem integration (Slack, CRMs, support tools)
- Data enrichment included at no cost
- Being part of Paddle gives it long-term stability

### Weaknesses

- Free tier is a loss leader — strategic incentive is to move users to Paddle billing
- Less analytical depth than ChartMogul (fewer custom dimensions, simpler segmentation)
- Innovation has slowed since Paddle acquisition — focus shifted to Paddle integration
- Metric calculation methodology is not transparent
- Users report some metrics diverge from their own calculations with no way to audit

---

## SaaSGrid (now Grid)

### Overview

SaaSGrid (rebranded to Grid) is the most finance-oriented tool in the category. It positions as a revenue intelligence platform rather than just subscription analytics, bridging the gap between billing data, CRM data, and accounting systems. It targets finance teams and CFOs rather than product or growth teams.

### Key Capabilities

- 150+ pre-configured SaaS metrics (far more than any competitor)
- Finance-to-CRM reconciliation
- ARR waterfall analysis and revenue bridge reporting
- Board-ready financial reporting
- Product usage trend overlays on revenue data
- Ad spend overlays for CAC and marketing ROI analysis
- Integrations: Stripe, Chargebee, Maxio, Recurly, Metronome, NetSuite, QuickBooks Online, Sage Intacct, Xero, Salesforce, HubSpot CRM, Google Sheets, Microsoft Excel, Google Slides

### Pricing

Starts at $5,000/year, with custom pricing for higher tiers based on data volume and feature requirements. 14-day free trial available.

### Strengths

- Deepest financial analytics — 150+ metrics, revenue bridge, waterfall analysis
- Strong accounting system integrations (NetSuite, QBO, Sage, Xero)
- Board-ready reporting out of the box
- CRM + billing + accounting data unification
- Designed for CFO/finance audience, not just product teams

### Weaknesses

- Expensive — $5K/year minimum puts it out of reach for early-stage companies
- Enterprise-focused pricing and feature set
- No free tier or meaningful self-serve onboarding
- Closed source
- Smaller community and less public documentation than competitors

---

## Comparison Summary

| Dimension | ChartMogul | Baremetrics | ProfitWell | SaaSGrid |
|---|---|---|---|---|
| Core Focus | Analytics + segmentation | Analytics + action (recovery) | Free metrics + paid optimization | Finance + revenue intelligence |
| Pricing | Free < $10K MRR, then $100+/mo | $108+/mo | Free (metrics) | $5,000+/year |
| Free Tier | Yes (< $10K MRR) | No | Yes (unlimited) | No (14-day trial) |
| Metric Count | 26+ | 28+ | ~20 | 150+ |
| Segmentation | Advanced (custom dimensions) | Basic (pre-built) | Basic | Advanced (finance-oriented) |
| Cohort Analysis | Advanced | Basic monthly | Basic | Advanced |
| Revenue Recovery | No | Yes (Recover) | Yes (Retain, paid) | No |
| Forecasting | Limited | Yes (Forecast+) | No | Yes |
| Benchmarking | No | Yes | Yes (34K+ companies) | No |
| Accounting Integration | No | Yes (QBO, Xero) | No | Yes (NetSuite, QBO, Sage, Xero) |
| CRM Built-in | Yes | No | No | No (integrates with external) |
| Open Source | No | No | No | No |
| Target Audience | Growth / Product teams | Growth / Ops teams | Everyone (free) / Growth | Finance / CFO |

---

## Key Observations

**No open-source option exists.** Every tool in this category is closed-source SaaS. Metric calculations are opaque — users cannot audit how MRR, churn, or LTV are computed. For companies with complex billing logic (usage-based, hybrid), this is a real problem because generic metric formulas may not reflect their actual business.

**The category is splitting.** ChartMogul and Baremetrics started in the same place but are diverging. ChartMogul is becoming a data platform, Baremetrics is becoming an action platform, ProfitWell is becoming a Paddle feature, and SaaSGrid is becoming a finance tool. This creates clear whitespace for a tool that focuses purely on transparent, customizable metric computation.

**Free tiers compress pricing power.** ProfitWell giving away metrics for free has made it hard for pure analytics tools to charge premium prices. ChartMogul responded with their own free tier. This dynamic makes open-source particularly viable — you cannot race to zero against free, but you can offer something free cannot: transparency, customizability, and data ownership.

**Billing source coverage is table stakes.** Every tool supports Stripe. Most support Braintree, Recurly, and Chargebee. But support for open-source billing engines (Lago, Kill Bill) is essentially non-existent. An open-source analytics tool with first-class Lago and Kill Bill support would have a natural community alignment advantage.

---

## Sources

- [ChartMogul Pricing](https://chartmogul.com/pricing/)
- [ChartMogul Subscription Analytics](https://chartmogul.com/subscription-analytics/)
- [Baremetrics Pricing](https://baremetrics.com/pricing)
- [Baremetrics vs ChartMogul vs ProfitWell](https://baremetrics.com/blog/baremetrics-vs-chartmogul-vs-profitwell)
- [Paddle — ProfitWell Metrics](https://www.paddle.com/profitwell-metrics)
- [Paddle — ProfitWell Acquisition](https://www.paddle.com/profitwell-acquisition)
- [SaaSGrid](https://www.withgrid.com/)
- [SaaSGrid — G2 Reviews 2026](https://www.g2.com/products/saasgrid/reviews)
- [QuantLedger — Baremetrics vs ProfitWell 2026](https://www.quantledger.app/blog/baremetrics-vs-profitwell)
- [QuantLedger — Baremetrics vs ChartMogul 2026](https://www.quantledger.app/blog/baremetrics-vs-chartmogul)
- [GrowthOptix — Baremetrics Alternatives 2026](https://www.growthoptix.com/blog/baremetrics-alternatives)
