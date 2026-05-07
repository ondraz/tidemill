# Canonical Vocabulary

Tidemill stores billing data from multiple providers (Stripe today, Lago and
Kill Bill on the roadmap) side-by-side in the same schema. Provider-specific
enum values would force every metric query and dashboard to special-case each
source. To avoid that, **connectors translate provider vocabulary into a
single canonical set at ingest time** — the values stored in core tables are
provider-agnostic.

This document specifies the canonical sets. New connectors must map their
provider's values onto these before writing.

## Plan interval

Stored in `plan.interval`. Connectors normalize so SQL and reports never
need a per-provider `CASE`.

| Canonical | Stripe `recurring.interval` | Lago `interval` | Kill Bill `BillingPeriod` |
|-----------|----------------------------|-----------------|---------------------------|
| `day`     | `day`                      | `daily`         | `DAILY`                   |
| `week`    | `week`                     | `weekly`        | `WEEKLY`                  |
| `month`   | `month`                    | `monthly`       | `MONTHLY`                 |
| `year`    | `year`                     | `yearly`        | `ANNUAL`                  |

`plan.interval_count` carries the multiplier (e.g. `interval='month',
interval_count=3` for quarterly). Stripe's `interval_count` is used directly;
Lago has no separate count (always 1); Kill Bill uses `BillingPeriod` codes
like `BIANNUAL` which connectors translate to `interval='month',
interval_count=6`.

## Pricing model

Stored in `plan.pricing_model` (renamed from the Stripe-flavored
`billing_scheme`). The canonical set covers every common SaaS pricing shape.

| Canonical    | Stripe `billing_scheme` / `recurring.usage_type`        | Lago `charge_model` | Kill Bill |
|--------------|---------------------------------------------------------|---------------------|-----------|
| `flat`       | `per_unit` + `usage_type='licensed'`                    | `standard`          | Recurring fixed |
| `tiered`     | `tiered` (graduated)                                    | `graduated`         | Tiered |
| `volume`     | `tiered` with `tiers_mode='volume'`                     | `volume`            | Volume |
| `usage_based`| `per_unit` + `usage_type='metered'`                     | `package`, `percentage`, `standard` with billable metric | Usage |

`plan.usage_type` (`licensed` | `metered`) is retained as a secondary
qualifier so Stripe's licensed-vs-metered distinction is preserved.

## Subscription status

Stored in `subscription.status`. The canonical set is intentionally small —
metric handlers only care about gross transitions (active vs. not-yet,
not-anymore, paused).

| Canonical          | Stripe `status`                                  | Lago `status`        | Kill Bill phase/state |
|--------------------|--------------------------------------------------|----------------------|-----------------------|
| `active`           | `active`                                         | `active`             | `ACTIVE` (non-trial phase) |
| `trialing`         | `trialing`                                       | `pending` (with `trial_ended_at` in future) | `TRIAL` phase |
| `pending_payment`  | `past_due`, `unpaid`, `incomplete`               | `pending`            | `PENDING` |
| `paused`           | `paused`                                         | (n/a — Lago has no pause) | `BUNDLE_PAUSE` |
| `canceled`         | `canceled`, `incomplete_expired`                 | `terminated`         | `CANCELLED` |

Connectors translate at ingest:
- Stripe `incomplete_expired` and `unpaid` → `canceled` when the metric
  meaning is "subscription has terminated for non-payment". The original
  Stripe value is preserved in `event_log.payload` for audit.
- Lago `terminated` → `canceled`.
- Kill Bill state machine has more granularity; map to the closest canonical
  bucket.

## Invoice status

Stored in `invoice.status`. Canonical set:

| Canonical       | Stripe        | Lago        | Kill Bill   |
|-----------------|---------------|-------------|-------------|
| `draft`         | `draft`       | `draft`     | `DRAFT`     |
| `open`          | `open`        | `finalized` | `COMMITTED` |
| `paid`          | `paid`        | `succeeded` | `PAID`      |
| `void`          | `void`        | `voided`    | `VOIDED`    |
| `uncollectible` | `uncollectible` | `failed`  | `WRITTEN_OFF` |

## Invoice line item type

Stored in `invoice_line_item.type`. The canonical set is small; provider
specifics go into the `description` field.

| Canonical       | Stripe (line item shape)                | Lago `fee_type` | Kill Bill `item_type` |
|-----------------|-----------------------------------------|-----------------|-----------------------|
| `subscription`  | `subscription` line                     | `subscription`  | `RECURRING`           |
| `usage`         | `subscription` with metered price       | `charge`        | `USAGE`               |
| `addon`         | `invoiceitem` (one-off charge)          | `add_on`        | `FIXED`               |
| `proration`     | line with `proration: true`             | `subscription` with split period | `REPAIR_ADJ` |
| `tax`           | `tax` line                              | `commitment` (tax-like) | `TAX`         |
| `discount`      | negative line with `discount`           | `credit`        | `CBA_ADJ`             |
| `credit`        | credit-note line                        | `credit_note`   | `CREDIT_ADJ`          |

## Payment status

Stored in `payment.status`. Canonical set:

| Canonical    | Stripe              | Lago     | Kill Bill |
|--------------|---------------------|----------|-----------|
| `pending`    | `requires_action`, `processing` | `pending` | `PENDING` |
| `succeeded`  | `succeeded`         | `succeeded` | `SUCCESS` |
| `failed`     | `failed`            | `failed` | `PAYMENT_FAILURE`, `PLUGIN_FAILURE` |
| `refunded`   | (charge refunded)   | `refunded` | `REFUND` |

## What lives in the connector vs. the schema

A connector's job is to translate **once, at ingest**. Core tables and event
payloads only ever contain canonical values. This means:

- Metric SQL filters by canonical values — `WHERE status = 'canceled'`, not a
  per-provider list.
- Dashboards display canonical values — they don't need to know whether the
  underlying source is Stripe or Lago.
- Adding a new connector is contained: implement `WebhookConnector.translate`
  (or the `DatabaseConnector` query methods) so the output uses canonical
  vocabulary, and the rest of the system works unchanged.

The original provider value, when it might be useful for debugging or
audit, is preserved in `event_log.payload` as raw JSON.
