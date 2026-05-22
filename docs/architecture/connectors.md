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
| `product.created` | `product.created` | Catalog sync — populates the `product` table used as a dimension in MRR / Churn cubes |
| `product.updated` | `product.updated` | |
| `product.deleted` | `product.deleted` | Marks the row inactive (plans may still reference it) |
| `price.created` | `plan.created` | Stripe Prices map onto the `plan` table; populates `interval`, `billing_scheme`, `usage_type`, etc. |
| `price.updated` | `plan.updated` | |
| `price.deleted` | `plan.deleted` | Marks the row inactive (subscriptions may still reference it) |
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

    Paginates through all objects and yields internal events. The caller
    publishes them to Kafka; from there the normal consumer pipeline
    (core state + metrics) processes them exactly like live webhooks.

    Order across types: products → prices (plans) → customers →
    subscriptions → invoices → payments.  Catalog objects come first so
    subscription rows can resolve their plan_id foreign key when the
    state consumer upserts them.

    Within each type the connector relies on Stripe's ``auto_paging_iter``,
    which streams pages **newest-first**.  Downstream handlers are
    idempotent and order-independent for catalog and entity events
    (``ON CONFLICT DO UPDATE`` upserts), so the iteration order does not
    affect the final state.  If a feature later requires strict
    chronological replay, sort each list locally before yielding.
    """
    stripe.api_key = self.config["api_key"]

    # 1a. Products (catalog — populates the `product` table)
    for prod in await self._paginate(stripe.Product.list):
        yield self._make_event("product.created",
            customer_id="",
            payload=self._product_payload(prod),
            occurred_at=datetime.fromtimestamp(prod["created"], tz=UTC))

    # 1b. Prices (catalog — emitted as `plan.*` internally, recurring only)
    for price in await self._paginate(stripe.Price.list):
        if not price.get("recurring"):
            continue  # one-time charges aren't plans
        yield self._make_event("plan.created",
            customer_id="",
            payload=self._price_payload(price),
            occurred_at=datetime.fromtimestamp(price["created"], tz=UTC))

    # 2. Customers
    for customer in await self._paginate(stripe.Customer.list, created={"gte": since}):
        yield self._make_event("customer.created",
            customer_id=customer["id"],
            payload=self._extract_customer(customer),
            occurred_at=datetime.fromtimestamp(customer["created"], tz=UTC))

    # 3. Subscriptions (includes current state + computed MRR)
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

    # 4. Invoices
    for invoice in await self._paginate(stripe.Invoice.list, created={"gte": since}):
        yield self._make_event("invoice.created", ...)
        if invoice["status"] == "paid":
            yield self._make_event("invoice.paid", ...)

    # 5. Payments
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

## Authoring a New Connector

This section is the contract a new connector author works against. The
canonical vocabulary tables in `canonical-vocabulary.md` are the
companion reference — they spell out the exact provider-to-canonical
value mappings the `translate()` method has to produce.

### The `translate()` contract

`WebhookConnector.translate(payload) -> list[Event]` is the only required
behavior. The events it returns flow through Kafka into the state
consumer and every metric handler. Five rules:

1. **Canonical event types.** Use the canonical names (`customer.created`,
   `subscription.created`, `subscription.activated`,
   `subscription.changed`, `subscription.canceled`, `subscription.churned`,
   `invoice.created`, `invoice.paid`, `payment.succeeded`,
   `coupon.created`, `credit_note.created`, …). The state-handler
   dispatch table at `tidemill/state.py:_HANDLERS` keys on the prefix
   before the first dot — anything outside this set is silently
   discarded.

2. **Canonical payload fields.** Every status/interval/usage-type/kind
   string in the payload must come from the `CANONICAL_*` tuples in
   `tidemill/connectors/base.py`. The state layer calls
   `validate_canonical()` before each write; a non-canonical value
   raises `CanonicalEnumViolation`, the worker DLQs the event, and the
   row in the core table stays untouched. Translate at the connector
   boundary, not later.

3. **Deterministic event IDs.** Use `make_event_id(source_id, type,
   external_id)` (UUID v5) so replays and duplicate webhooks are
   idempotent — `event_log` has `ON CONFLICT (id) DO NOTHING` and the
   metric consumers track resolved DLQ rows by `(event_id, consumer)`.

4. **Subscription items go in `items: [...]`.** When the source models
   subscriptions as a set of items (Stripe, Chargebee 2.0), emit the
   breakdown on every `subscription.created` and `subscription.changed`
   payload — the state handler re-materializes via DELETE+INSERT. For
   single-plan sources (Recurly, Lago, Kill Bill), emit a single-item
   list mirroring the totals so the table stays populated.

5. **Don't pre-aggregate.** Forward what happened, not the metric — the
   metric handlers compute MRR/churn/retention from the events. The one
   exception is `mrr_cents` on subscription event payloads (see "MRR
   override" below) — that's a connector-provided hint, not a
   pre-aggregation.

### Signature verification

`verify_signature(payload, signature) -> bool` is **mandatory** —
`WebhookConnector`'s default now raises `NotImplementedError` so a
connector that forgets to wire up signature verification gets a loud
failure during integration testing, not a silent auth-bypass in
production.

Three legal overrides:

- **Real verification** (Stripe, QuickBooks): use the provider's
  HMAC/SDK helper. Return `True` only when the signature checks out
  against the configured secret.
- **No-op for test harnesses**: explicitly `return True` and document
  why (e.g. the test connector has no signature scheme).
- **Lenient with explicit guard** (the pattern Stripe and QuickBooks
  use today): when the webhook secret is unconfigured, fall back to
  `return True`. This is appropriate for local development; production
  deployments must set the secret.

The webhook routes (`api/routers/webhooks.py`,
`connectors/stripe/routes.py`) only call `verify_signature` when a
signature header is present. A connector whose provider doesn't send
signatures is fine, but bear in mind that a request arriving *without*
a signature header bypasses verification entirely — that's a routing
concern, not a connector concern.

### MRR computation: shared utility vs. server-provided override

Two paths, picked per connector:

**A. Compute via `compute_mrr_cents()`.** When the source exposes only
plan-level fields (`amount_cents`, `interval`, `interval_count`,
`quantity`), import the utility from `tidemill.connectors.base` and
call it per subscription item:

```python
from tidemill.connectors.base import compute_mrr_cents

item_mrr = compute_mrr_cents(
    amount_cents=price["unit_amount"],
    interval=recurring["interval"],
    interval_count=recurring.get("interval_count", 1) or 1,
    quantity=item.get("quantity", 1) or 1,
)
```

This is what the Stripe connector does
(`tidemill/connectors/stripe/connector.py:_compute_mrr`).

**B. Pass through a server-provided value.** When the source already
computes MRR (Chargebee's `subscription.mrr`, Recurly's billing
summary), put it on the event payload as `mrr_cents` and the state
layer trusts it verbatim. This avoids re-implementing the source's
proration math and is the recommended path when available.

In both cases, **metered items contribute 0 to subscription MRR** —
their revenue flows through the trailing-usage path (see
`tidemill/metrics/mrr/usage.py`). Emit a `subscription_item` row for
them with `mrr_cents=0` so the item count breakdown stays correct.

### Canonical enum validation

Every status / interval / kind / payment-method-type string in your
event payload must be one of the values in the corresponding
`CANONICAL_*` tuple. The state layer runs `validate_canonical(value,
allowed, field)` before each write:

| Field                                | Canonical tuple                       |
|--------------------------------------|---------------------------------------|
| `plan.interval`                      | `CANONICAL_INTERVALS`                 |
| `plan.pricing_model`                 | `CANONICAL_PRICING_MODELS`            |
| `plan.usage_type`                    | `CANONICAL_USAGE_TYPES`               |
| `subscription.status`                | `CANONICAL_SUBSCRIPTION_STATUSES`     |
| `invoice.status`                     | `CANONICAL_INVOICE_STATUSES`          |
| `invoice_line_item.kind`             | `CANONICAL_LINE_ITEM_KINDS`           |
| `payment.payment_method_type`        | `CANONICAL_PAYMENT_METHOD_TYPES`      |
| `coupon.duration`                    | `CANONICAL_COUPON_DURATIONS`          |
| `credit_note.status`                 | `CANONICAL_CREDIT_NOTE_STATUSES`      |
| `credit_note.reason`                 | `CANONICAL_CREDIT_NOTE_REASONS`       |
| `account.account_type` (expense)     | `CANONICAL_ACCOUNT_TYPES`             |
| `bill.status` (expense)              | `CANONICAL_BILL_STATUSES`             |
| `expense.payment_type` (expense)     | `CANONICAL_PAYMENT_TYPES`             |

`None` is always legal (treated as "unknown"); any non-`None` string
must come from the tuple. A non-canonical write raises
`CanonicalEnumViolation`, the worker records the failure in
`dead_letter_event` with `error_type='canonical_enum_violation'`, and
the core table stays untouched — so a malformed connector
dead-letters its own events instead of corrupting analytics.

### Webhook Connector scaffold (Chargebee, Recurly, Paddle, …)

1. Create `tidemill/connectors/myplatform/{__init__.py, connector.py,
   routes.py}` (single-file at `tidemill/connectors/myplatform.py` is
   also fine if there's no separate route or client).
2. Subclass `WebhookConnector`. Set `source_type` to the registered
   name.
3. Implement `translate(payload) -> list[Event]` per the contract
   above. Cross-check every status/interval/kind against the canonical
   vocabulary table in `canonical-vocabulary.md`.
4. Implement `verify_signature(payload, signature)` using the
   provider's HMAC/SDK helper. Don't fall back to `return True`
   without a guard; if the provider has no signature scheme, document
   the override.
5. Pick the MRR path (compute via `compute_mrr_cents()` or pass
   through the source's MRR). Emit `items: [...]` on subscription
   events even for single-plan sources.
6. Optionally implement `backfill(since) -> AsyncIterator[Event]` for
   first-run history ingestion. Use the same `translate()` event
   types so the state and metric layers handle backfill identically
   to live webhooks.
7. Decorate with `@register("myplatform")` so the registry picks it up.

### Database Connector scaffold (Lago, Kill Bill, …)

1. Create `tidemill/connectors/myplatform.py`.
2. Subclass `DatabaseConnector`. Implement `get_active_subscriptions`,
   `get_mrr_cents`, `get_subscription_changes`, `get_customers`,
   `get_invoices` against the billing engine's PostgreSQL.
3. Return canonical-shaped rows (status ∈
   `CANONICAL_SUBSCRIPTION_STATUSES`, etc.) so metric SQL never sees
   provider vocabulary.
4. Decorate with `@register("myplatform")`.

### Expense Connector scaffold (Xero, FreshBooks, Wave, Sage, …)

1. Create `tidemill/connectors/myplatform/`.
2. Subclass `ExpenseConnector` (inherits `WebhookConnector`).
3. Implement the four normalize/extract methods
   (`normalize_account_type`, `normalize_bill_status`,
   `normalize_payment_type`, `extract_dimensions`) mapping native
   vocabulary to `CANONICAL_ACCOUNT_TYPES` / `CANONICAL_BILL_STATUSES`
   / `CANONICAL_PAYMENT_TYPES` / a `dimensions` JSON dict.
4. Implement `translate()` and `backfill()` (or `fetch_and_translate()`
   for ID-only webhooks like QBO).
5. Emit canonical expense event types: `vendor.*`, `account.*`,
   `bill.*`, `expense.*`, `bill_payment.*`. The schema, state
   handlers, and expenses metric are all platform-neutral.
6. Override `verify_signature()` with the provider's HMAC scheme.
7. Decorate with `@register("myplatform")`.

### Pre-merge checklist

- [ ] Every status / interval / kind in event payloads is in the
      corresponding `CANONICAL_*` tuple.
- [ ] `verify_signature` is overridden (no implicit base raise).
- [ ] Event IDs come from `make_event_id`.
- [ ] Subscription events carry `items: [...]` (single-plan sources
      emit a one-item list).
- [ ] `translate()` is idempotent — feeding the same webhook twice
      produces events with identical IDs and the state upserts
      collapse cleanly.
- [ ] A unit test covers `translate()` for at least the lifecycle
      events you map (create / update / cancel / change).
- [ ] If `backfill()` is implemented, it emits the same event types
      as live webhooks — no separate "historical" types.
