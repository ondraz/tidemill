---
title: stripe-python CHANGELOG (v15.0.0 → v16.0.0)
url: https://github.com/stripe/stripe-python/blob/master/CHANGELOG.md
publisher: Stripe
published: 2026-09-30
accessed: 2026-10-25
type: changelog
tags: [stripe, api-version, changelog, endive, dahlia]
status: captured
---

# stripe-python CHANGELOG — billing-relevant extract

Captured from the SDK changelog because Stripe's own API changelog
(`docs.stripe.com/changelog`) was unreachable from the capture environment. The
SDK changelog is generated from Stripe's OpenAPI spec, so it records the same
API surface changes, but without Stripe's prose explanations. Cross-checked
against the stripe 16.0.0 sdist from PyPI (`stripe/_api_version.py`,
`stripe/_subscription.py`, `stripe/_invoice.py`).

## Pinned API versions

| SDK | Date | Pinned API version |
|---|---|---|
| 15.0.0 | 2026-03-25 | `2026-03-25.dahlia` |
| 16.0.0 | 2026-09-30 | `2026-09-30.endive` |

## 16.0.0 — `2026-09-30.endive` (extracted, verbatim where quoted)

- "Add support for `pause` method on resource `Subscription`". SDK docstring:
  "Pauses a subscription by transitioning it to the paused status. A paused
  subscription does not generate invoices and will not advance to new billing
  periods. The subscription can be resumed later using the resume endpoint.
  Cannot pause subscriptions with attached schedules."
- "Add support for `status_details` on `Invoice` and `Subscription`".
  - `Subscription.status_details.paused.subscription.type` ∈
    `final_payment_failure`, `first_payment_failure`, `pause_requested`,
    `system`, `trial_end_without_payment_method`; plus `transitioned_at`.
  - `Invoice.status_details.uncollectible.reason` ∈ `max_payment_attempts`,
    `payment_not_received`, `subscription_canceled`, `subscription_paused`,
    `user_forgiven`.
- "Add support for `current_trial` on … `SubscriptionItem`" (item-level trials).
- "Add support for `pause_schedules` on … `SubscriptionSchedule`".
- "Add support for `billing_cycle_anchor` on `Subscription.TrialSetting.EndBehavior`".
- "Add support for `cancel_at_period_end` on `Subscription.PendingUpdate`".
- ⚠️ "Remove support for `payment_method_types` on `PaymentIntentConfirmParams`,
  `PaymentIntentCreateParams`, … and `checkout.SessionCreateParams`" (request
  params only; the response field remains).
- ⚠️ `SubscriptionModifyParams.billing_cycle_anchor` changes type to `billing_cycle_anchor_param`.
- ⚠️ SDK: path parameters are positional-only on service methods and on
  dual-style resource methods; `StripeObject.request()` removed;
  `stripe.Reversal` renamed `stripe.TransferReversal`.
- New `product_catalog.TrialOffer` resource; `V1CustomerSubscriptionPausedEvent`
  and related v1 event notifications.

## 15.x — Dahlia line (2026-04 → 2026-09, additive)

- `billing.FeedbackOption` resource; `feedback_option` on
  `Subscription.CancellationDetail` (custom cancellation-survey options).
- `billed_until` on `SubscriptionItem`; `billing_schedules` on `Subscription`;
  new `cancel_at` value `max_billed_until`.
- `amount_paid_off_stripe` on `Invoice`.
- `custom_fields`, `description`, `footer` on `Subscription.InvoiceSetting`.
- `managed_payments` on `Subscription`, `PaymentIntent`, `Checkout.Session`.
- New payment-method types on invoice/subscription payment settings: `twint`,
  `satispay`, `billie`, `blik`, `alipay`, `mb_way`; new `PaymentMethod.type`
  values `bizum`, `scalapay`, `sunbit`.

## Metering surface (from the 16.0.0 sdist)

- `stripe/billing/` ships `Meter`, `MeterEvent`, `MeterEventAdjustment`,
  `MeterEventSummary`. Summary docstring: "an aggregated view of a customer's
  billing meter events within a specified timeframe."
- No `UsageRecord` resource exists in the SDK (legacy usage records are gone).
