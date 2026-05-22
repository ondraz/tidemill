"""Idempotent schema migrations for canonical-vocabulary renames.

Tidemill's schema is managed by ``metadata.create_all`` — additive only.
This module runs the small set of DDL changes that ``create_all`` can't
express (column renames, in-place type widenings). It's invoked once per
API/CLI/worker startup, before ``create_all``; each step is wrapped to be
safe to re-run.

PostgreSQL-only by design (the production target). SQLite test fixtures
build the schema from the current model with no historical data, so no
migration is needed there — the function returns early on non-PG dialects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection


async def migrate_schema(conn: AsyncConnection) -> None:
    """Run pending in-place DDL migrations before ``create_all``.

    Idempotent: each step probes ``information_schema`` before issuing DDL,
    so re-runs are no-ops. Safe to call on a freshly-created database
    (every step short-circuits when the old shape isn't present).
    """
    if conn.dialect.name != "postgresql":
        return

    await _rename_cancel_at_period_end(conn)
    # Data-backfill steps run *after* ``create_all`` adds the new tables.


async def backfill_after_create_all(conn: AsyncConnection) -> None:
    """Data backfills that require the new tables to already exist.

    Called after :func:`migrate_schema` and ``create_all`` so the new
    tables ``create_all`` provisioned (subscription_item, coupon,
    credit_note) are guaranteed to be present. Idempotent.
    """
    if conn.dialect.name != "postgresql":
        return

    await _backfill_subscription_items(conn)


async def _backfill_subscription_items(conn: AsyncConnection) -> None:
    """One placeholder ``subscription_item`` row per existing subscription.

    Old subscriptions stored a single plan + total MRR on the subscription
    row. The new ``subscription_item`` table breaks that out, but we don't
    have the per-item native IDs for historical rows — so we synthesize
    one placeholder item per subscription, using ``external_id ||
    '#item-0'`` as a clearly-synthetic key. As soon as the next webhook
    arrives for the subscription, the connector emits the real items and
    ``_replace_subscription_items`` (state.py) deletes the placeholder
    and inserts the proper rows.

    Idempotent: the LEFT JOIN guards against re-creating items for
    subscriptions that already have any item row.
    """
    await conn.execute(
        text(
            "INSERT INTO subscription_item"
            " (id, source_id, external_id, subscription_id, plan_id,"
            "  quantity, mrr_cents, mrr_base_cents, currency, created_at)"
            " SELECT"
            "  gen_random_uuid()::text,"
            "  s.source_id,"
            "  s.external_id || '#item-0',"
            "  s.id,"
            "  s.plan_id,"
            "  s.quantity,"
            "  s.mrr_cents,"
            "  s.mrr_base_cents,"
            "  s.currency,"
            "  s.created_at"
            " FROM subscription s"
            " LEFT JOIN subscription_item si ON si.subscription_id = s.id"
            " WHERE si.id IS NULL"
            " ON CONFLICT ON CONSTRAINT uq_subscription_item_source DO NOTHING"
        )
    )


async def _rename_cancel_at_period_end(conn: AsyncConnection) -> None:
    """``subscription.cancel_at_period_end`` → ``pending_cancellation``.

    The original name was Stripe-shaped and didn't generalize to Chargebee
    (``non_renewing``) or Recurly (``state='canceled' AND expires_at >
    now()``); the new name is provider-agnostic.
    """
    result = await conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns"
            " WHERE table_name = 'subscription'"
            "   AND column_name = 'cancel_at_period_end'"
        )
    )
    if result.scalar() is None:
        return
    await conn.execute(
        text("ALTER TABLE subscription RENAME COLUMN cancel_at_period_end TO pending_cancellation")
    )
