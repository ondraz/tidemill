# Canonical Vocabulary

Tidemill stores billing data from multiple providers side-by-side in the
same schema. The reference implementation is Stripe (webhook ingestion);
Lago and Kill Bill are P1 same-database connectors; Chargebee, Recurly,
Paddle, and Maxio/Chargify are documented as future targets. Each table
below lists the provider-native equivalents for every gateway we expect
to support — connector authors map onto these values at ingest time, and
the rest of the system never sees provider-specific strings.

Provider-specific enum values would force every metric query and dashboard
to special-case each source. To avoid that, **connectors translate
provider vocabulary into a single canonical set at ingest time** — the
values stored in core tables are provider-agnostic.

This document specifies the canonical sets. New connectors must map their
provider's values onto these before writing.

## Plan interval

Stored in `plan.interval`. Connectors normalize so SQL and reports never
need a per-provider `CASE`.

| Canonical | Stripe `recurring.interval` | Chargebee `item_price.period_unit` | Recurly `Plan.interval_unit` | Lago `interval` | Kill Bill `BillingPeriod` |
|-----------|------------------------------|-------------------------------------|------------------------------|------------------|---------------------------|
| `day`     | `day`                        | `day`                               | `days` (with `interval_length`) | `daily`     | `DAILY`                   |
| `week`    | `week`                       | `week`                              | (n/a — emit as 7 `days`)     | `weekly`         | `WEEKLY`                  |
| `month`   | `month`                      | `month`                             | `months` (length=1)          | `monthly`        | `MONTHLY`                 |
| `year`    | `year`                       | `year`                              | `months` (length=12)         | `yearly`         | `ANNUAL`                  |

`plan.interval_count` carries the multiplier (e.g. `interval='month',
interval_count=3` for quarterly). Stripe's `interval_count` and
Chargebee's `period` are used directly; Recurly's `interval_length`
multiplies the unit; Lago has no separate count (always 1); Kill Bill
uses `BillingPeriod` codes like `BIANNUAL` which connectors translate to
`interval='month', interval_count=6`.

## Pricing model

Stored in `plan.pricing_model` (renamed from the Stripe-flavored
`billing_scheme`). The canonical set covers every common SaaS pricing shape.

| Canonical    | Stripe `billing_scheme` / `recurring.usage_type`        | Chargebee `item_price.pricing_model` | Recurly `Plan.pricing_model` / `Addon.tier_type` | Lago `charge_model` | Kill Bill |
|--------------|---------------------------------------------------------|---------------------------------------|---------------------------------------------------|---------------------|-----------|
| `flat`       | `per_unit` + `usage_type='licensed'`                    | `flat_fee` / `per_unit`               | `fixed` plan / addon `flat`                       | `standard`          | Recurring fixed |
| `tiered`     | `tiered` (graduated)                                    | `tiered` (graduated)                  | addon `tiered`                                    | `graduated`         | Tiered |
| `volume`     | `tiered` with `tiers_mode='volume'`                     | `volume`                              | addon `volume`                                    | `volume`            | Volume |
| `usage_based`| `per_unit` + `usage_type='metered'`                     | `per_unit` on metered item / `addon_type='metered'` | addon with `usage_type` set        | `package`, `percentage`, `standard` with billable metric | Usage |

`plan.usage_type` (`licensed` | `metered`) is retained as a secondary
qualifier so Stripe's licensed-vs-metered distinction is preserved. For
Chargebee map `addon_type='metered'` (or item_price on a metered item)
to `metered`; for Recurly, `addon.usage_type` being non-null maps to
`metered`.

## Subscription status

Stored in `subscription.status`. The canonical set is intentionally small —
metric handlers only care about gross transitions (active vs. not-yet,
not-anymore, paused).

| Canonical          | Stripe `status`                                  | Chargebee `Subscription.status`                | Recurly `Subscription.state`                  | Lago `status`        | Kill Bill phase/state |
|--------------------|--------------------------------------------------|------------------------------------------------|------------------------------------------------|----------------------|-----------------------|
| `active`           | `active`                                         | `active`, `non_renewing` (also sets `pending_cancellation=true`) | `active`                  | `active`             | `ACTIVE` (non-trial phase) |
| `trialing`         | `trialing`                                       | `in_trial`                                     | `active` with `trial_ends_at` in future        | `pending` (with `trial_ended_at` in future) | `TRIAL` phase |
| `pending_payment`  | `past_due`, `unpaid`, `incomplete`               | `paused` with `pause_reason='dunning'`         | `failed`                                       | `pending`            | `PENDING` |
| `paused`           | `paused`                                         | `paused`                                       | `paused`                                       | (n/a — Lago has no pause) | `BUNDLE_PAUSE` |
| `canceled`         | `canceled`, `incomplete_expired`                 | `cancelled`                                    | `canceled`, `expired`                          | `terminated`         | `CANCELLED` |

Connectors translate at ingest:
- Stripe `incomplete_expired` and `unpaid` → `canceled` when the metric
  meaning is "subscription has terminated for non-payment". The original
  Stripe value is preserved in `event_log.payload` for audit.
- Chargebee `non_renewing` stays `active` for the current period but
  populates `pending_cancellation=true` so churn forecasts see the
  signal.
- Recurly `expired` → `canceled` (cohort funnel treats both terminal).
- Lago `terminated` → `canceled`.
- Kill Bill state machine has more granularity; map to the closest canonical
  bucket.

## Invoice status

Stored in `invoice.status`. Canonical set:

| Canonical       | Stripe          | Chargebee `Invoice.status`           | Recurly `Invoice.state`         | Lago        | Kill Bill   |
|-----------------|-----------------|--------------------------------------|---------------------------------|-------------|-------------|
| `draft`         | `draft`         | `pending`, `posted`                  | `pending`                       | `draft`     | `DRAFT`     |
| `open`          | `open`          | `payment_due`, `not_paid`            | `processing`, `past_due`        | `finalized` | `COMMITTED` |
| `paid`          | `paid`          | `paid`                               | `paid`                          | `succeeded` | `PAID`      |
| `void`          | `void`          | `voided`                             | `voided`                        | `voided`    | `VOIDED`    |
| `uncollectible` | `uncollectible` | `not_paid` (after dunning exhausted) | `failed`, `closed`              | `failed`    | `WRITTEN_OFF` |

## Invoice line item type

Stored in `invoice_line_item.type`. The canonical set is small; provider
specifics go into the `description` field.

| Canonical       | Stripe (line item shape)                | Chargebee `InvoiceLineItem.entity_type` / flags | Recurly `LineItem.type` / `add_on_type` | Lago `fee_type` | Kill Bill `item_type` |
|-----------------|-----------------------------------------|-------------------------------------------------|------------------------------------------|-----------------|-----------------------|
| `subscription`  | `subscription` line                     | `plan` / `plan_item_price`                      | `charge` with `add_on_code=null` (plan)  | `subscription`  | `RECURRING`           |
| `usage`         | `subscription` with metered price       | `addon` with `addon_type='metered'`             | `charge` with `usage_type` on addon      | `charge`        | `USAGE`               |
| `addon`         | `invoiceitem` (one-off charge)          | `addon` / `charge` / one-time `charge_item_price` | `charge` with addon (non-usage)        | `add_on`        | `FIXED`               |
| `proration`     | line with `proration: true`             | line with `is_proration=true`                   | `adjustment` flagged proration           | `subscription` with split period | `REPAIR_ADJ` |
| `tax`           | `tax` line                              | line of type `tax`                              | per-line `tax` block                     | `commitment` (tax-like) | `TAX`         |
| `discount`      | negative line with `discount`           | line tied to a `coupon` redemption              | negative `adjustment` from coupon        | `credit`        | `CBA_ADJ`             |
| `credit`        | credit-note line                        | `credit_note` line                              | `credit` line                            | `credit_note`   | `CREDIT_ADJ`          |

## Payment status

Stored in `payment.status`. Canonical set:

| Canonical    | Stripe                          | Chargebee `Transaction.status`     | Recurly `Transaction.status`    | Lago        | Kill Bill |
|--------------|---------------------------------|-------------------------------------|---------------------------------|-------------|-----------|
| `pending`    | `requires_action`, `processing` | `needs_attention`, `timeout`        | `pending`                       | `pending`   | `PENDING` |
| `succeeded`  | `succeeded`                     | `success`                           | `success`                       | `succeeded` | `SUCCESS` |
| `failed`     | `failed`                        | `failure`, `voided` (pre-capture)   | `failed`, `declined`            | `failed`    | `PAYMENT_FAILURE`, `PLUGIN_FAILURE` |
| `refunded`   | (charge refunded)               | Transaction `type=refund`           | Transaction `action=refund`     | `refunded`  | `REFUND`  |

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

## Coupon duration

Stored in `coupon.duration`. Tells dashboards whether a discount applies
once, forever, or for a bounded number of months.

| Canonical    | Stripe `coupon.duration` | Chargebee `coupon.duration_type` | Recurly `coupon.duration` |
|--------------|--------------------------|-----------------------------------|---------------------------|
| `forever`    | `forever`                | `forever`                         | `forever`                 |
| `once`       | `once`                   | `one_time`                        | `single_use`              |
| `repeating`  | `repeating` (with `duration_in_months`) | `limited_period` (with `period_unit + period`) | `temporal` (with `temporal_amount + temporal_unit`) |

## Credit note status

Stored in `credit_note.status`.

| Canonical | Stripe `credit_note.status` | Chargebee `credit_note.status` | Recurly `credit_payment.action` |
|-----------|------------------------------|---------------------------------|---------------------------------|
| `issued`  | `issued`                     | `refunded`, `refund_due`, `adjusted` | `issued` |
| `void`    | `void`                       | `voided`                        | `voided`  |

## Credit note reason

Stored in `credit_note.reason`. Matches Stripe's enum, with `other` as the
catchall for providers that lack a structured reason.

| Canonical               | Stripe `credit_note.reason`     | Chargebee `credit_note.reason_code`            |
|-------------------------|----------------------------------|-------------------------------------------------|
| `duplicate`             | `duplicate`                      | `duplicate`                                     |
| `fraudulent`            | `fraudulent`                     | `fraudulent`                                    |
| `order_change`          | `order_change`                   | `order_change`, `cancellation`                  |
| `product_unsatisfactory`| `product_unsatisfactory`         | `product_unsatisfactory`, `service_unsatisfactory` |
| `other`                 | (n/a — Stripe always has one)    | `other`, `write_off`, `chargeback`              |

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
CANONICAL_COUPON_DURATIONS = ("forever", "once", "repeating")
CANONICAL_CREDIT_NOTE_STATUSES = ("issued", "void")
CANONICAL_CREDIT_NOTE_REASONS = (
    "duplicate", "fraudulent", "order_change", "product_unsatisfactory", "other",
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
