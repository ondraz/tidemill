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

## Pending cancellation

Stored in `subscription.pending_cancellation` (Boolean). `True` when the
subscription is scheduled to cancel at the end of the current period but
is still billing until then.

| Canonical                  | Stripe                                            | Chargebee                          | Recurly                                        | Lago                       |
|----------------------------|---------------------------------------------------|------------------------------------|------------------------------------------------|----------------------------|
| `pending_cancellation=true`| `cancel_at_period_end=true`                       | `non_renewing` flag                | `state='canceled' AND expires_at > now()`      | (n/a — Lago lacks the semantic) |

The original field name (`cancel_at_period_end`) leaked Stripe's vocabulary.
Connectors map their native equivalent at ingest.

## Payment method type

Stored in `payment.payment_method_type`. The canonical set is intentionally
coarse — finer-grained provider tokens (`bancontact`, `ideal`, etc.) lose
meaning across gateways, so each connector buckets them into the five
canonical values plus `other`.

| Canonical        | Stripe `payment_method_types[]`                                   | Chargebee `payment_method`                | Recurly `account.billing_info.type` |
|------------------|-------------------------------------------------------------------|-------------------------------------------|-------------------------------------|
| `card`           | `card`, `card_present`, `klarna`, `affirm`, `afterpay_clearpay`   | `card`                                    | `credit_card`                       |
| `bank_transfer`  | `us_bank_account`, `customer_balance`                             | `bank_transfer`                           | `bank_account`                      |
| `direct_debit`   | `sepa_debit`, `bacs_debit`, `becs_debit`, `acss_debit`, `ach_debit` | `direct_debit`                          | `bank_account_info` (with debit)    |
| `wallet`         | `link`, `wechat_pay`, `alipay`, `cashapp`                         | `apple_pay`, `google_pay`                 | `apple_pay`, `amazon_pay`           |
| `paypal`         | `paypal`                                                          | `paypal_express_checkout`                 | `paypal`                            |
| `other`          | anything else                                                     | anything else                             | anything else                       |

## Codified enums

The canonical sets are mirrored in code as tuples in
`tidemill.connectors.base`:

```python
CANONICAL_INTERVALS = ("day", "week", "month", "year")
CANONICAL_PRICING_MODELS = ("flat", "tiered", "volume", "usage_based")
CANONICAL_USAGE_TYPES = ("licensed", "metered")
CANONICAL_SUBSCRIPTION_STATUSES = (
    "active", "trialing", "pending_payment", "paused", "canceled",
)
CANONICAL_INVOICE_STATUSES = ("draft", "open", "paid", "void", "uncollectible")
CANONICAL_LINE_ITEM_KINDS = (
    "subscription", "usage", "addon", "proration", "tax", "discount",
    "credit", "other",
)
CANONICAL_PAYMENT_STATUSES = ("pending", "succeeded", "failed", "refunded")
CANONICAL_PAYMENT_METHOD_TYPES = (
    "card", "bank_transfer", "direct_debit", "wallet", "paypal", "other",
)
```

The state layer calls `validate_canonical(value, ALLOWED, field)` before
each canonical-typed write. A non-canonical value raises
`CanonicalEnumViolation`, which the worker catches and persists to
`dead_letter_event` with `error_type='canonical_enum_violation'`. The bad
value never reaches a core table — a malformed connector dead-letters the
event instead of corrupting analytics.

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
