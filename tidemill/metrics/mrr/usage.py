"""Trailing-3-month usage component of MRR.

Stripe rolls metered usage into invoice line items at billing finalization.
On each ``invoice.paid`` event we sum the ``kind='usage'`` lines for the
affected subscription, bucket them into the invoice's billing month, and
recompute the subscription's trailing-3-month average. A change in the
rolling mean updates ``metric_mrr_snapshot.usage_mrr_*`` and emits an
expansion or contraction movement tagged ``source='usage'``.

Why trailing 3 months: smooths month-to-month spikes, matches industry
convention (ChartMogul / Baremetrics), and produces a stable expansion /
contraction signal even for bursty workloads. See
``docs/definitions.md#mrr`` for the formal definition.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from tidemill.events import Event

logger = logging.getLogger(__name__)

USAGE_TRAILING_MONTHS = 3


def _month_start(value: datetime | date) -> date:
    """Return the UTC first-of-month date for *value*.

    Accepts either a ``datetime`` (tz-aware preferred — naive is treated as
    UTC, matching the rest of the codebase) or a ``date``.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return date(value.year, value.month, 1)
    return date(value.year, value.month, 1)


async def recompute_usage_component_for_invoice(
    db: AsyncSession,
    event: Event,
) -> None:
    """Bucket an invoice's usage lines and refresh the trailing-3m component.

    No-op when the invoice carries no ``kind='usage'`` lines or cannot be
    associated with a subscription (e.g. a one-off invoice).

    Args:
        db: Active async session for the consumer transaction.
        event: An ``invoice.paid`` event. Must carry ``external_id`` in its
            payload; ``subscription_external_id`` is preferred but the
            invoice row is consulted as a fallback.

    Raises:
        FxRateMissingError: Propagated from line-item materialization (FX
            already happened in ``state.py`` so this should not normally
            fire from here, but the dead-letter contract is preserved).
    """
    payload = event.payload
    invoice_eid = payload.get("external_id")
    if not invoice_eid:
        return

    sub_eid = payload.get("subscription_external_id")
    if not sub_eid:
        result = await db.execute(
            text(
                "SELECT s.external_id"
                " FROM invoice i"
                " LEFT JOIN subscription s ON s.id = i.subscription_id"
                " WHERE i.source_id = :src AND i.external_id = :eid"
            ),
            {"src": event.source_id, "eid": invoice_eid},
        )
        row = result.first()
        sub_eid = row[0] if row else None
    if not sub_eid:
        return

    usage_lines = await db.execute(
        text(
            "SELECT li.amount_cents, li.amount_base_cents, li.currency,"
            "       i.period_start AS inv_period_start"
            " FROM invoice_line_item li"
            " JOIN invoice i ON i.id = li.invoice_id"
            " WHERE i.source_id = :src"
            "   AND i.external_id = :eid"
            "   AND li.kind = 'usage'"
        ),
        {"src": event.source_id, "eid": invoice_eid},
    )
    lines = list(usage_lines.mappings().all())
    if not lines:
        return

    period_basis = lines[0]["inv_period_start"] or event.occurred_at
    bucket = _month_start(period_basis)
    total_cents = sum(int(li["amount_cents"] or 0) for li in lines)
    total_base_cents = sum(int(li["amount_base_cents"] or 0) for li in lines)
    currency = (lines[0]["currency"] or "USD").upper()

    await db.execute(
        text(
            "INSERT INTO metric_mrr_usage_component"
            " (id, source_id, customer_id, subscription_id, period_start,"
            "  usage_cents, usage_base_cents, currency, computed_at)"
            " VALUES (:id, :src, :cid, :sid, :ps, :uc, :ucb, :cur, :now)"
            " ON CONFLICT ON CONSTRAINT uq_mrr_usage_component_sub_period"
            " DO UPDATE SET"
            "  usage_cents = metric_mrr_usage_component.usage_cents"
            "    + EXCLUDED.usage_cents,"
            "  usage_base_cents = metric_mrr_usage_component.usage_base_cents"
            "    + EXCLUDED.usage_base_cents,"
            "  computed_at = EXCLUDED.computed_at"
        ),
        {
            "id": str(uuid.uuid4()),
            "src": event.source_id,
            "cid": event.customer_id,
            "sid": sub_eid,
            "ps": bucket,
            "uc": total_cents,
            "ucb": total_base_cents,
            "cur": currency,
            "now": event.occurred_at,
        },
    )

    await _apply_trailing_average(
        db,
        event=event,
        subscription_ext_id=sub_eid,
        currency=currency,
    )


async def _apply_trailing_average(
    db: AsyncSession,
    *,
    event: Event,
    subscription_ext_id: str,
    currency: str,
) -> None:
    """Recompute the rolling mean and emit a movement on change.

    Reads the most recent ``USAGE_TRAILING_MONTHS`` buckets and integer-divides
    by the count actually present (so a customer with only one or two months
    of history gets a fair mean rather than a deflated one).
    """
    buckets = await db.execute(
        text(
            "SELECT usage_cents, usage_base_cents"
            " FROM metric_mrr_usage_component"
            " WHERE source_id = :src AND subscription_id = :sid"
            " ORDER BY period_start DESC LIMIT :n"
        ),
        {
            "src": event.source_id,
            "sid": subscription_ext_id,
            "n": USAGE_TRAILING_MONTHS,
        },
    )
    rows = buckets.mappings().all()
    if not rows:
        return

    n = len(rows)
    new_usage_cents = sum(int(r["usage_cents"] or 0) for r in rows) // n
    new_usage_base = sum(int(r["usage_base_cents"] or 0) for r in rows) // n

    snap_result = await db.execute(
        text(
            "SELECT subscription_mrr_cents, subscription_mrr_base_cents,"
            "       usage_mrr_cents, usage_mrr_base_cents"
            " FROM metric_mrr_snapshot"
            " WHERE source_id = :src AND subscription_id = :sid"
        ),
        {"src": event.source_id, "sid": subscription_ext_id},
    )
    snap = snap_result.mappings().first()
    if snap is None:
        # Subscription event hasn't created a snapshot row yet. The next
        # subscription lifecycle event will land at usage=0; this same code
        # path on the *next* invoice.paid will then emit the right
        # expansion movement. Skipping here keeps idempotency.
        logger.debug(
            "metric_mrr_snapshot row missing for subscription %s; skipping recompute",
            subscription_ext_id,
        )
        return

    prior_usage_cents = int(snap["usage_mrr_cents"] or 0)
    prior_usage_base = int(snap["usage_mrr_base_cents"] or 0)
    delta_cents = new_usage_cents - prior_usage_cents
    delta_base = new_usage_base - prior_usage_base
    if delta_cents == 0 and delta_base == 0:
        return

    sub_cents = int(snap["subscription_mrr_cents"] or 0)
    sub_base = int(snap["subscription_mrr_base_cents"] or 0)

    await db.execute(
        text(
            "UPDATE metric_mrr_snapshot SET"
            "  usage_mrr_cents = :uc,"
            "  usage_mrr_base_cents = :ucb,"
            "  mrr_cents = :combined,"
            "  mrr_base_cents = :combined_base,"
            "  snapshot_at = :now"
            " WHERE source_id = :src AND subscription_id = :sid"
        ),
        {
            "uc": new_usage_cents,
            "ucb": new_usage_base,
            "combined": sub_cents + new_usage_cents,
            "combined_base": sub_base + new_usage_base,
            "now": event.occurred_at,
            "src": event.source_id,
            "sid": subscription_ext_id,
        },
    )

    movement_type = "expansion" if delta_base > 0 else "contraction"
    # Synthetic event_id: LTV also consumes invoice.paid and writes a row
    # keyed on event.id, but movements are independent. Suffixing isolates
    # this insert from any future consumer that might write its own
    # movement against the same Kafka event.
    movement_event_id = f"{event.id}#usage"

    await db.execute(
        text(
            "INSERT INTO metric_mrr_movement"
            " (id, event_id, source_id, customer_id, subscription_id,"
            "  movement_type, source,"
            "  amount_cents, amount_base_cents, currency, occurred_at)"
            " VALUES (:id, :eid, :src, :cid, :sid, :mt, 'usage',"
            "         :amt, :amtb, :cur, :at)"
            " ON CONFLICT (event_id) DO NOTHING"
        ),
        {
            "id": str(uuid.uuid4()),
            "eid": movement_event_id,
            "src": event.source_id,
            "cid": event.customer_id,
            "sid": subscription_ext_id,
            "mt": movement_type,
            "amt": delta_cents,
            "amtb": delta_base,
            "cur": currency.upper(),
            "at": event.occurred_at,
        },
    )
