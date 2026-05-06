# Connectors

> Adapters that connect billing systems to the analytics engine.
> Last updated: March 2026

## Design

There are two types of connectors, matching the [dual architecture](overview.md):

1. **Webhook connectors** (ingestion mode) — receive webhooks, translate them into [internal events](events.md), and publish to Kafka. This is the primary integration path. Stripe is the reference implementation.
2. **Database connectors** (same-database mode) — query the billing engine's PostgreSQL directly. No webhooks, no Kafka, no ETL. Available for open-source billing engines (Lago, Kill Bill) that expose their database.

### Webhook Connector (Ingestion Mode) — Primary

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator
from tidemill.events import Event


class WebhookConnector(ABC):
    """Translates billing system webhooks into internal events.
    This is the primary connector type — works with any billing system
    that exposes webhooks."""

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Identifier: 'stripe'."""
        ...

    @abstractmethod
    def translate(self, webhook_payload: dict) -> list[Event]:
        """Translate a raw webhook payload into internal events.
        Synchronous — pure data transformation, no I/O.
        Returns an empty list if the webhook type is not relevant."""
        ...

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """Verify webhook signature. Synchronous — pure crypto, no I/O."""
        return True

    async def backfill(self, since: datetime | None = None) -> AsyncIterator[Event]:
        """Pull historical data from the billing system API.
        Async — makes HTTP requests to the billing system.
        Yields the same internal events as translate()."""
        raise NotImplementedError
```

**Webhook flow:**

```
Billing System                Connector              Kafka
     │                            │                     │
     │  POST /webhooks/{source}   │                     │
     ├───────────────────────────►│                     │
     │                            │  verify_signature() │
     │                            │  translate()        │
     │                            │                     │
     │                            │  publish(events)    │
     │                            ├────────────────────►│
     │        200 OK              │                     │
     │◄───────────────────────────┤                     │
```

The webhook endpoint returns 200 immediately after publishing to Kafka. Processing happens asynchronously in consumers.

### Database Connector (Same-Database Mode) — Alternative

```python
from abc import ABC, abstractmethod
from datetime import date
from sqlalchemy.ext.asyncio import AsyncEngine


class DatabaseConnector(ABC):
    """Queries a billing engine's database directly for metric computation.
    Zero ETL, zero latency — but only available for billing engines that
    expose their PostgreSQL (Lago, Kill Bill).

    All methods are async — they issue SQL against the billing engine's PostgreSQL.
    """

    def __init__(self, engine: AsyncEngine):
        self.engine = engine

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Identifier: 'lago', 'killbill'."""
        ...

    @abstractmethod
    async def get_active_subscriptions(self, at: date | None = None) -> list[dict]:
        """Return active subscriptions with MRR contribution."""
        ...

    @abstractmethod
    async def get_mrr_cents(self, at: date | None = None) -> int:
        """Return total MRR in cents (original currency) at a point in time."""
        ...

    @abstractmethod
    async def get_mrr_usd_cents(self, at: date | None = None) -> int:
        """Return total MRR in USD cents at a point in time."""
        ...

    @abstractmethod
    async def get_subscription_changes(self, start: date, end: date) -> list[dict]:
        """Return subscription state changes in a period.
        Each change includes: type (new/expansion/contraction/churn/reactivation),
        amount_cents, amount_usd_cents, currency, customer_id, subscription_id, occurred_at."""
        ...

    @abstractmethod
    async def get_customers(self, at: date | None = None) -> list[dict]:
        """Return customer records."""
        ...

    @abstractmethod
    async def get_invoices(self, start: date, end: date) -> list[dict]:
        """Return invoices in a period."""
        ...
```

**Data flow (same-database):**

```
Billing Engine PostgreSQL          Database Connector         Metric
  ┌────────────────────┐         ┌──────────────────┐      ┌──────────────┐
  │ subscriptions      │◄── SQL ─┤ get_mrr_cents()  │◄─────┤ metric.query │
  │ fees / invoices    │         │ get_changes()    │      │              │
  │ customers          │         │ get_customers()  │      │              │
  └────────────────────┘         └──────────────────┘      └──────────────┘
```

No event bus. No consumer processes. The metric calls the database connector at query time.

## Stripe Connector (P0) — Reference Implementation

Stripe is the primary connector. It uses the webhook/Kafka ingestion architecture.

### Webhook Translation

| Stripe Webhook | Internal Event(s) | Notes |
|---------------|-------------------|-------|
| `customer.created` | `customer.created` | Copies `address.country` onto the payload so segmentation by country works out of the box |
| `customer.updated` | `customer.updated` | |
| `customer.deleted` | `customer.deleted` | |
| `customer.subscription.created` | `subscription.created`, optionally `subscription.trial_started` | If `status=trialing`, also emit trial event |
| `customer.subscription.updated` | Depends on what changed (see below) | Most complex translation |
| `customer.subscription.deleted` | `subscription.churned` | Forwards `cancellation_details.feedback` as `cancel_reason` |
| `customer.subscription.trial_will_end` | (ignored, handled via status change) | |
| `invoice.created` | `invoice.created` | |
| `invoice.paid` | `invoice.paid` | |
| `invoice.voided` | `invoice.voided` | |
| `invoice.marked_uncollectible` | `invoice.uncollectible` | |
| `payment_intent.succeeded` | `payment.succeeded` | |
| `payment_intent.payment_failed` | `payment.failed` | |
| `charge.refunded` | `payment.refunded` | |

### Subscription Update Translation

`customer.subscription.updated` is Stripe's catch-all. The connector inspects `previous_attributes` to determine what changed:

```python
def _translate_subscription_updated(self, webhook: dict) -> list[Event]:
    sub = webhook["data"]["object"]
    prev = webhook["data"].get("previous_attributes", {})
    events = []

    # Status change
    if "status" in prev:
        old_status = prev["status"]
        new_status = sub["status"]

        if old_status == "trialing" and new_status == "active":
            events.append(self._make_event("subscription.trial_converted", ...))
            events.append(self._make_event("subscription.activated", ...))
        elif old_status == "trialing" and new_status in ("canceled", "unpaid"):
            events.append(self._make_event("subscription.trial_expired", ...))
        elif new_status == "active" and old_status != "active":
            events.append(self._make_event("subscription.activated", ...))
        elif new_status == "canceled":
            events.append(self._make_event("subscription.canceled", ...))
        elif new_status == "paused":
            events.append(self._make_event("subscription.paused", ...))

    # Plan or quantity change (while active)
    if "items" in prev or "quantity" in prev:
        prev_mrr = self._compute_mrr(prev)
        new_mrr = self._compute_mrr(sub)
        events.append(self._make_event("subscription.changed",
            prev_mrr_cents=prev_mrr, new_mrr_cents=new_mrr, ...))

    return events
```

### MRR Computation

```python
def _compute_mrr(self, subscription: dict) -> int:
    """Compute MRR in cents from a Stripe subscription object."""
    total = 0
    for item in subscription.get("items", {}).get("data", []):
        price = item["price"]
        qty = item.get("quantity", 1)
        amount = price["unit_amount"] * qty
        interval = price["recurring"]["interval"]
        interval_count = price["recurring"]["interval_count"]

        match interval:
            case "month": total += amount // interval_count
            case "year":  total += amount // (12 * interval_count)
            case "week":  total += int(amount * 52 / (12 * interval_count))
            case "day":   total += int(amount * 365 / (12 * interval_count))
    return total
```

### Backfill (First Run)

On first deployment, the analytics database is empty — no customers, no subscriptions, no metric data. The `backfill()` method pulls the full history from Stripe's API and yields internal events identical to what webhooks would have produced.

```python
async def backfill(self, since: datetime | None = None) -> AsyncIterator[Event]:
    """Pull historical data from the Stripe API.

    Paginates through all objects and yields internal events in
    chronological order. The caller publishes them to Kafka; from
    there the normal consumer pipeline (core state + metrics) processes
    them exactly like live webhooks.

    Order: customers → subscriptions → invoices → payments.
    Within each type, objects are yielded oldest-first.
    """
    stripe.api_key = self.config["api_key"]

    # 1. Customers
    for customer in await self._paginate(stripe.Customer.list, created={"gte": since}):
        yield self._make_event("customer.created",
            customer_id=customer["id"],
            payload=self._extract_customer(customer),
            occurred_at=datetime.fromtimestamp(customer["created"], tz=UTC))

    # 2. Subscriptions (includes current state + computed MRR)
    for sub in await self._paginate(stripe.Subscription.list, created={"gte": since}):
        yield self._make_event("subscription.created",
            customer_id=sub["customer"],
            payload={
                "subscription_id": sub["id"],
                "plan_id": sub["items"]["data"][0]["price"]["id"],
                "mrr_cents": self._compute_mrr(sub),
                "status": sub["status"],
            },
            occurred_at=datetime.fromtimestamp(sub["created"], tz=UTC))
        if sub["status"] == "active":
            yield self._make_event("subscription.activated", ...)
        elif sub["status"] == "canceled":
            yield self._make_event("subscription.churned", ...)

    # 3. Invoices
    for invoice in await self._paginate(stripe.Invoice.list, created={"gte": since}):
        yield self._make_event("invoice.created", ...)
        if invoice["status"] == "paid":
            yield self._make_event("invoice.paid", ...)

    # 4. Payments
    for pi in await self._paginate(stripe.PaymentIntent.list, created={"gte": since}):
        if pi["status"] == "succeeded":
            yield self._make_event("payment.succeeded", ...)

async def _paginate(self, list_fn, **params) -> AsyncIterator[dict]:
    """Auto-paginate a Stripe list endpoint."""
    params["limit"] = 100
    while True:
        page = await list_fn(**params)
        for obj in page["data"]:
            yield obj
        if not page["has_more"]:
            break
        params["starting_after"] = page["data"][-1]["id"]
```

**Triggering backfill:**

```bash
# Via API
curl -X POST localhost:8000/api/sources/{source_id}/backfill

# Via CLI
tidemill backfill --source stripe

# Programmatic
async for event in stripe_connector.backfill(since=None):
    await bus.publish(event)
```

The backfill publishes events to Kafka through the same pipeline as live webhooks. The core state consumer and metric consumers process them normally, building up the base tables and metric tables from scratch.

**Idempotency:** Each event carries a deterministic `id` derived from the Stripe object ID and event type. If backfill is run twice, `handle_event()` implementations use `ON CONFLICT DO NOTHING` (via the `event_id UNIQUE` constraint on metric tables) to skip duplicates.

**Incremental backfill:** Pass `since` to only fetch objects created after a given timestamp. Useful for catching up after a period of missed webhooks.

## Lago Connector (P1)

Lago is the reference implementation for same-database mode. Because Lago uses PostgreSQL as its primary database, the analytics engine can query Lago's tables directly — zero ETL, zero latency, zero per-transaction cost. This is a strong differentiator for Lago users, but lower priority than the Stripe integration.

### Integration Architecture

The Lago connector is a `DatabaseConnector` that issues SQL queries against Lago's PostgreSQL tables. The analytics engine either:

- **Shares Lago's PostgreSQL** (recommended) — `metric_*` tables are created in a separate schema within the same database
- **Connects to Lago's PostgreSQL as read-only** — analytics has its own database for `metric_*` tables and queries Lago's DB for billing data

### Key Lago Tables Queried

| Lago Table | Analytics Use |
|-----------|---------------|
| `subscriptions` | Active subscriptions, status, plan, billing period |
| `fees` | Individual fee line items (subscription, usage, add-ons) — the source of truth for MRR |
| `invoices` | Invoice records, payment status, totals |
| `customers` | Customer records, external IDs, metadata |
| `plans` | Plan definitions, intervals, pricing |
| `charges` | Usage-based pricing charges |

### MRR Computation (Direct SQL)

Lago's `fees` table provides fee-type separation (subscription vs. usage vs. add-ons), which gives more accurate MRR than inferring from plan prices:

```python
async def get_mrr_usd_cents(self, at: date | None = None) -> int:
    """Query Lago's fees table for current MRR in USD cents."""
    async with self.engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT COALESCE(SUM(
                CASE
                    WHEN p.interval = 'monthly'    THEN f.amount_cents
                    WHEN p.interval = 'yearly'     THEN f.amount_cents / 12
                    WHEN p.interval = 'quarterly'  THEN f.amount_cents / 3
                    WHEN p.interval = 'weekly'     THEN CAST(f.amount_cents * 52.0 / 12 AS BIGINT)
                END
                * fx.rate
            ), 0)
            FROM fees f
            JOIN subscriptions s ON f.subscription_id = s.id
            JOIN plans p ON s.plan_id = p.id
            JOIN LATERAL (
                SELECT rate FROM fx_rate
                WHERE from_currency = f.currency AND to_currency = 'USD'
                  AND date <= COALESCE(:at, CURRENT_DATE)
                ORDER BY date DESC LIMIT 1
            ) fx ON true
            WHERE s.status = 'active'
              AND f.fee_type = 'subscription'
              AND f.created_at <= COALESCE(:at, CURRENT_DATE)
        """), {"at": at})
        return result.scalar() or 0
```

### Subscription Changes (Direct SQL)

```python
async def get_subscription_changes(self, start: date, end: date) -> list[dict]:
    """Query subscription state transitions from Lago's tables."""
    async with self.engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT ...
        """), {"start": start, "end": end})
        return [row._asdict() for row in result]
```

### Why Same-Database for Lago

1. **Direct PostgreSQL access** — same-database queries eliminate ETL complexity
2. **Fee-type separation** — Lago natively separates subscription, usage, and add-on fees, giving accurate MRR without inference
3. **Event-based architecture** — Lago processes 15,000 events/sec, aligns with our event model
4. **Open-source** — fully inspectable schema, no vendor lock-in

## Kill Bill Connector (P1)

Kill Bill also uses PostgreSQL (or MySQL) as its primary database, making it a natural fit for same-database mode.

### Integration Architecture

Like Lago, Kill Bill's connector is a `DatabaseConnector`. When Kill Bill's analytics plugin is installed, the connector reads `current_mrr` directly from the `analytics_bundles` table and `prev_mrr`/`next_mrr` from `analytics_subscription_transitions`. This is more accurate than computing from catalog prices.

Fallback: compute from catalog plan price + interval.

### Key Kill Bill Tables

| Kill Bill Table | Analytics Use |
|----------------|---------------|
| `subscriptions` | Subscription state and plan |
| `bundles` | Subscription bundles |
| `accounts` | Customer accounts |
| `invoices` / `invoice_items` | Invoice and line item data |
| `payments` / `payment_transactions` | Payment records |
| `analytics_bundles` (plugin) | Pre-computed MRR |
| `analytics_subscription_transitions` (plugin) | State change history |

### Event Type Mapping (Webhook Fallback)

Kill Bill can also operate in ingestion mode via `ExtBusEvent` webhooks:

| Kill Bill Event Type | Internal Event(s) | Notes |
|---------------------|-------------------|-------|
| `ACCOUNT_CREATION` | `customer.created` | |
| `ACCOUNT_CHANGE` | `customer.updated` | |
| `SUBSCRIPTION_CREATION` | `subscription.created` | |
| `SUBSCRIPTION_PHASE` | `subscription.activated` or `subscription.trial_started` | Depends on `phaseType` |
| `SUBSCRIPTION_CHANGE` | `subscription.changed` | Fetch prev/new plan from API |
| `SUBSCRIPTION_CANCEL` | `subscription.canceled` | |
| `SUBSCRIPTION_EXPIRED` | `subscription.churned` | |
| `SUBSCRIPTION_UNCANCEL` | `subscription.reactivated` | |
| `BUNDLE_PAUSE` | `subscription.paused` (per sub in bundle) | |
| `BUNDLE_RESUME` | `subscription.resumed` (per sub in bundle) | |
| `INVOICE_CREATION` | `invoice.created` | |
| `INVOICE_PAYMENT_SUCCESS` | `invoice.paid` + `payment.succeeded` | |
| `INVOICE_PAYMENT_FAILED` | `payment.failed` | |

## QuickBooks Online Connector (P1) — Expense Source

QuickBooks is fundamentally an accounting platform, not a billing one. We integrate it as Tidemill's first **expense data source** so customers can compute burn rate, runway, gross margin, and cash-flow forecasts alongside Stripe revenue. Subscription/MRR concepts are intentionally absent.

### Integration Architecture

```
Tidemill   ←OAuth2 ↔ QBO Auth Server (token refresh)
   │
   │ webhook notifications (entity IDs only)
   │
QBO Sandbox/Production ──API── REST ─→ QuickBooksClient ─→ Event(s) ─→ Kafka
                              fetch
```

QBO webhooks are **notifications**, not full payloads — they only carry `{realmId, name, id, operation}`. The route handler must call the QBO REST API to fetch the full entity, then translate. For that reason `translate()` returns `[]`; `fetch_and_translate()` is the entry point.

### `ExpenseConnector` ABC

Lives in `tidemill.connectors.base`. Every expense-side connector (QBO today; Xero / FreshBooks / Wave / Sage tomorrow) implements four methods to map its native vocabulary onto Tidemill's canonical enums:

| Method | Returns one of |
|---|---|
| `normalize_account_type(native)` | `expense, cogs, income, asset, liability, equity, other` |
| `normalize_bill_status(native)` | `open, partial, paid, voided` |
| `normalize_payment_type(native)` | `cash, credit_card, check, bank_transfer, other` |
| `extract_dimensions(line)` | `dict` with `class` / `department` / `project` keys (any subset) |

Native values are always preserved on `metadata_` (`native_account_type`, etc.) so connector-level audits can recover the original string.

### Cross-platform mapping

| Concept | QuickBooks Online | Xero | FreshBooks |
|---|---|---|---|
| Vendor | `Vendor` | `Contact` (`IsSupplier=true`) | `Vendor` |
| Chart of accounts | `Account` (`AccountType`) | `Account` (`Type`) | `Category` |
| Accrual payable | `Bill` | `Invoice` (`Type=ACCPAY`) | `Bill` |
| Cash purchase | `Purchase` | `BankTransaction` (`Type=SPEND`) | `Expense` |
| Bill payment | `BillPayment` | `Payment` against ACCPAY | `Payment` |
| Tagging | `Class` + `Department` | `TrackingCategory` (×2) | `Project` |

A future Xero connector reuses the **entire schema, event types, state handlers, and expenses metric** — only the `XeroConnector` class itself is new code.

### OAuth 2.0 Flow

QBO requires OAuth 2.0 with refresh tokens (~1h access, ~100d refresh). One Intuit Developer app can connect to many QBO companies (`realmId`s); we materialise each as a separate `connector_source` row keyed `quickbooks-{realmId}`.

```
GET  /api/connectors/quickbooks/oauth/start    → redirect to Intuit
GET  /api/connectors/quickbooks/oauth/callback → exchange code, persist
                                                 tokens in connector_source.config
POST /api/webhooks/quickbooks?source_id=...    → Intuit-signed webhooks
```

Token refresh is automatic in `QuickBooksClient`; the latest access/refresh tokens are written back to `connector_source.config` after every refresh.

### Backfill

Order matters because state handlers resolve FKs by `(source_id, external_id)`:

1. `Vendor`
2. `Account`
3. `Bill`
4. `Purchase`
5. `BillPayment`

Each is paginated via QBO's Query endpoint (`SELECT * FROM <Entity>` with `STARTPOSITION` / `MAXRESULTS`) and yielded as canonical events.

## Connector Registry

```python
from tidemill.connectors import register, get_connector

# Webhook connector (ingestion mode) — primary
@register("stripe")
class StripeConnector(WebhookConnector):
    ...

# Database connector (same-database mode) — alternative
@register("lago")
class LagoConnector(DatabaseConnector):
    ...

# Usage — webhook connector (translate is sync, backfill is async)
stripe = get_connector("stripe", config={"api_key": "sk_...", "webhook_secret": "whsec_..."})
events = stripe.translate(raw_payload)           # sync
async for event in stripe.backfill(since=...):   # async
    await bus.publish(event)

# Usage — database connector (async)
lago = get_connector("lago", engine=lago_async_engine)
mrr = await lago.get_mrr_usd_cents()
```

## Adding a New Connector

### Webhook Connector (for any billing system with webhooks)

1. Create `tidemill/connectors/myplatform.py`
2. Subclass `WebhookConnector`
3. Implement `translate()` and optionally `backfill()`
4. Map each vendor webhook to the appropriate internal events
5. Implement MRR computation for the vendor's subscription/pricing model
6. Decorate with `@register("myplatform")`

### Database Connector (for billing engines with accessible databases)

1. Create `tidemill/connectors/myplatform.py`
2. Subclass `DatabaseConnector`
3. Implement `get_active_subscriptions()`, `get_mrr_cents()`, `get_subscription_changes()`, etc.
4. Write SQL queries against the billing engine's tables
5. Decorate with `@register("myplatform")`

### Expense Connector (for accounting platforms)

1. Create `tidemill/connectors/myplatform/`
2. Subclass `ExpenseConnector` (inherits `WebhookConnector`)
3. Implement the four normalize/extract methods (`normalize_account_type`, `normalize_bill_status`, `normalize_payment_type`, `extract_dimensions`)
4. Implement `translate()` + `backfill()` (or `fetch_and_translate()` for ID-only webhooks)
5. Emit canonical event types: `vendor.*`, `account.*`, `bill.*`, `expense.*`, `bill_payment.*`
6. Decorate with `@register("myplatform")`

The schema, state handlers, expenses metric, and Kafka topics are all platform-neutral — no schema changes are needed for any accounting platform that fits the canonical model.
