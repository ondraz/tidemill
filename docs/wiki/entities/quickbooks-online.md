---
title: QuickBooks Online
description: Accounting platform and Tidemill's first expense-side integration — the source that makes cost analysis possible alongside revenue.
type: entity
tags: [accounting, data-source, expense, implemented]
updated: 2026-07-23
---

# QuickBooks Online

> Tidemill's first expense source, and the reason the data model has a cost side at all.

---

## What it is

Intuit's cloud accounting platform. In the analytics category it usually appears as a
*supporting* integration — [Baremetrics](baremetrics.md) pulls it for forecasting actuals,
[SaaSGrid](saasgrid.md) for finance reconciliation. Its relevant objects are vendors,
accounts, bills, purchases (expenses) and bill payments.

## Key facts

| | |
|---|---|
| Category | Accounting / expense source |
| Licence | Proprietary SaaS |
| Auth | OAuth 2.0 (Intuit Developer), sandbox and production environments |
| Webhooks | ID-only payloads, HMAC-SHA256 signed with a verifier token |
| Tidemill integration | `ExpenseConnector`, registered as `quickbooks` |
| Status | **Implemented** (P1) |

## Relevance to Tidemill

QuickBooks Online is Tidemill's **first and so far only expense connector**
(`tidemill/connectors/quickbooks/`). It is what turns Tidemill from a revenue-only tool
into one that can also see the cost side — see [expenses](../../architecture/expenses.md).

It defined a third connector shape. [Stripe](stripe-billing.md) and
[Chargebee](chargebee.md) are `WebhookConnector`s; [Lago](lago.md) and
[Kill Bill](kill-bill.md) are `DatabaseConnector`s; QBO required `ExpenseConnector`,
with a `fetch_and_translate()` path because its webhooks carry only object IDs and the
records must be fetched back before translation. See
[connectors](../../architecture/connectors.md).

Its accounting vocabulary was deliberately **not** adopted directly. The expense model is
platform-neutral — canonical account types, bill statuses and payment types designed so
Xero, FreshBooks, Wave or Sage can map onto the same events (`vendor.*`, `account.*`,
`bill.*`, `expense.*`, `bill_payment.*`) without touching state handlers or the expenses
metric. This is the same discipline the
[canonical vocabulary](../../architecture/canonical-vocabulary.md) applies on the revenue
side.

Expense analytics is also the prerequisite for CAC, which remains
[P1 and unimplemented](../../architecture/overview.md).

## Related

- [Chargebee](chargebee.md) — canonical-vocabulary discipline on the revenue side
- [SaaSGrid](saasgrid.md), [Baremetrics](baremetrics.md) — competitors using QBO differently
- [Tidemill](tidemill.md)

## Sources

- [Expenses architecture](../../architecture/expenses.md) — data model and canonical enums
- [Connectors](../../architecture/connectors.md) — `ExpenseConnector` pattern
- [Testing](../../development/testing.md) — sandbox OAuth and expense seeding
