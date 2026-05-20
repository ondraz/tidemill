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
