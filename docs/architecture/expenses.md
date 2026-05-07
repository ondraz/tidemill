# Expenses

> Tidemill's expense-side data model — vendors, chart of accounts, bills, expenses, bill payments. Designed to accept any accounting platform (QuickBooks Online, Xero, FreshBooks, Wave, Sage) without schema changes.
> Last updated: May 2026

## Why expenses live in Tidemill

Tidemill started revenue-only. Once Stripe data was flowing, the next class of question customers asked was about the *other* side of the income statement: "what's our burn?", "how much runway do we have?", "what's our gross margin given AWS hosting + contractor costs?". Answering those needs an expense source. QuickBooks Online is the first integration.

## Data model

Every table is platform-neutral. Connector-specific values live in `metadata_` JSON; cross-cutting tagging dimensions (project / class / department) live in `bill_line.dimensions` / `expense_line.dimensions` JSON. The dual `*_cents` / `*_base_cents` money convention matches the revenue side.

```
vendor ──┐
         │
account  │
   │     │
   │     ▼
   │   bill ─── bill_line   (accrual payable; status: open/partial/paid/voided)
   │     │
   │     ▼
   │   bill_payment
   │
   └── expense ─── expense_line   (direct cash/credit purchase, no bill)
```

| Table | Notes |
|---|---|
| `vendor` | Counterparty for bills/expenses. Mirror of `customer` on the revenue side. |
| `account` | Chart of Accounts. `account_type` is one of the **canonical enums** below. Tree via `parent_external_id`. |
| `bill` | A/P document with status `{open, partial, paid, voided}`. |
| `bill_line` | Line item linking the bill to an `account` and (optionally) tagging dimensions. |
| `expense` | Direct purchase (cash/credit/check). `payment_type` is canonical. |
| `expense_line` | Line item, same shape as `bill_line`. |
| `bill_payment` | Payment applied against a bill. Used to compute open A/P balances. |

## Canonical enums

Defined in `tidemill.connectors.base`:

| Enum | Values |
|---|---|
| `account.account_type` | `expense, cogs, income, asset, liability, equity, other` |
| `bill.status` | `open, partial, paid, voided` |
| `expense.payment_type` | `cash, credit_card, check, bank_transfer, other` |

Each `ExpenseConnector` maps its native vocabulary into these. The original native string is preserved in `metadata_` (e.g. `metadata_.native_account_type = "Cost of Goods Sold"`).

## Event flow

Connectors emit events of the form:

- `vendor.created` / `vendor.updated` / `vendor.deleted`
- `account.created` / `account.updated`
- `bill.created` / `bill.updated` / `bill.paid` / `bill.voided`
- `expense.created` / `expense.updated` / `expense.voided`
- `bill_payment.created`

`Event.customer_id` carries the **realm ID** (or equivalent tenant identifier) so events for the same accounting tenant share a Kafka partition and stay strictly ordered.

The state consumer (`tidemill.state`) handles every prefix above with the same `INSERT … ON CONFLICT DO UPDATE` pattern as the revenue side. Lines on bills/expenses are bulk-replaced (DELETE + INSERT) on every header update because most accounting APIs regenerate line IDs.

## Metrics

Today: **`expenses`** — total / `by_account_type` / `by_vendor` / monthly `series`. Reads `bill_line UNION ALL expense_line` joined to `account` + `vendor`, summing `amount_base_cents`. Voided bills/expenses are excluded.

Endpoints:

```
GET /api/metrics/expenses?start=&end=                  → {total_base_cents, line_count}
GET /api/metrics/expenses/by_account_type?start=&end=  → [{account_type, amount_base_cents, line_count}]
GET /api/metrics/expenses/by_vendor?start=&end=        → [{vendor_name, amount_base_cents, line_count}]
GET /api/metrics/expenses/series?start=&end=&interval= → [{period, account_type, amount_base_cents}]
```

Future metrics planned on top of this same data:

- **Burn rate** — monthly total over the last `n` months.
- **Gross margin** — Stripe revenue (existing) − COGS-classified expenses, by month.
- **Runway** — cash balance ÷ trailing-3-month burn (needs a bank-balance source).
- **Forecast** — extrapolate recurring expense series forward.

## Adding another expense source

See [connectors.md](connectors.md#expense-connector-for-accounting-platforms). The work is:

1. Subclass `ExpenseConnector` in `tidemill/connectors/<platform>/`.
2. Implement `translate()` (or `fetch_and_translate()`) for vendor / account / bill / expense / bill payment.
3. Implement the four normalize/extract methods.
4. Add OAuth (or whatever auth the platform uses).
5. Register with `@register("<platform>")`.

Schema, state handlers, expenses metric, and tests stay untouched.
