---
title: chargebee-python CHANGELOG (v3.18.0 → v3.29.0)
url: https://github.com/chargebee/chargebee-python/blob/master/CHANGELOG.md
publisher: Chargebee
published: 2026-09-24
accessed: 2026-10-25
type: changelog
tags: [chargebee, changelog, api]
status: captured
---

# chargebee-python CHANGELOG — billing-relevant extract

Captured from the SDK changelog, which mirrors Chargebee's API v2 changes. The
official API changelog (`chargebee.com/docs`) was unreachable from the capture environment.

| SDK | Date | Billing-relevant change |
|---|---|---|
| 3.18.0 | 2026-02-06 | `decommissioned` attribute added to `Subscription` |
| 3.23.0 | 2026-06-08 | `exclude` query param removed from `list_invoices` (it was added in an earlier 2026 release) |
| 3.23.0–3.29.0 | 2026-06 → 2026-09 | Omnichannel (app-store) subscriptions expanded: `OmnichannelSubscriptionItemMetric`, `purchased_at` / `updated_at` attributes and filters, `omnichannel_subscription_item_updated` / `_recovered` events |
| 3.26.0 | 2026-07-21 | `exchange_rates` added to `Invoice` and `CreditNote`; `decommissioned` filter on `list_subscriptions` and `export_subscriptions` |
| 3.26.0–3.28.0 | 2026-07 → 2026-08 | Credits ledger: `GrantBlock`, `LedgerAccountBalance`, `ledger_operations`; several `GrantBlock` amount attributes deprecated; `start_balance` / `end_balance` removed from `LedgerOperation` |
| 3.27.0 | 2026-07-30 | `export_subscription_ramps`; `include_cancellation_day_in_billing` on cancel estimates |
| 3.29.0 | 2026-09-24 | Latest release at capture |

Removals in this window touch only `QuoteEntitlement`, `LedgerOperation` and
the `list_invoices` `exclude` parameter. None are subscription, invoice or
customer webhook payload fields.
