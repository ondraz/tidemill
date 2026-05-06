"""Shared test fixtures."""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import date, datetime

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tidemill.models import metadata

# ── Fix Python 3.12+ sqlite3 datetime adapter deprecation ───────────────
# aiosqlite triggers the deprecated default adapters; registering explicit
# ones silences the warnings globally for the test process.

sqlite3.register_adapter(datetime, lambda v: v.isoformat())
sqlite3.register_adapter(date, lambda v: v.isoformat())
sqlite3.register_converter("datetime", lambda b: datetime.fromisoformat(b.decode()))
sqlite3.register_converter("date", lambda b: date.fromisoformat(b.decode()))

# Map PostgreSQL named constraints → column lists for SQLite ON CONFLICT.
_CONSTRAINT_COLS = {
    "uq_customer_source": "(source_id, external_id)",
    "uq_product_source": "(source_id, external_id)",
    "uq_plan_source": "(source_id, external_id)",
    "uq_subscription_source": "(source_id, external_id)",
    "uq_invoice_source": "(source_id, external_id)",
    "uq_payment_source": "(source_id, external_id)",
    "uq_fx_rate": "(date, from_currency, to_currency)",
    "uq_mrr_snapshot_sub": "(source_id, subscription_id)",
    "uq_churn_state_customer": "(source_id, customer_id)",
    "uq_retention_cohort_customer": "(source_id, customer_id)",
    "uq_retention_activity": "(source_id, customer_id, active_month)",
    "uq_trial_sub": "(source_id, subscription_id)",
    "uq_customer_attr_source_cust_key": "(source_id, customer_id, key)",
    "uq_vendor_source": "(source_id, external_id)",
    "uq_account_source": "(source_id, external_id)",
    "uq_bill_source": "(source_id, external_id)",
    "uq_expense_source": "(source_id, external_id)",
    "uq_bill_payment_source": "(source_id, external_id)",
}

_PG_CONSTRAINT_RE = re.compile(
    r"ON CONFLICT ON CONSTRAINT (\w+)",
    re.IGNORECASE,
)


@pytest.fixture
async def db():
    """Async SQLite in-memory session with PG-compat SQL rewriting."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @sa_event.listens_for(engine.sync_engine, "before_cursor_execute", retval=True)
    def _adapt_pg_sql(conn, cursor, statement, parameters, context, executemany):
        def _replace(m: re.Match[str]) -> str:
            name = m.group(1)
            cols = _CONSTRAINT_COLS.get(name)
            if cols:
                return f"ON CONFLICT {cols}"
            return m.group(0)

        statement = _PG_CONSTRAINT_RE.sub(_replace, statement)
        # SQLite uses MAX()/MIN() where PostgreSQL uses GREATEST()/LEAST()
        statement = statement.replace("GREATEST(", "MAX(")
        statement = statement.replace("LEAST(", "MIN(")
        return statement, parameters

    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


# ── PostgreSQL fixture (integration tests) ──────────────────────────────

_PG_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://subscriptions:password@localhost:5432/subscriptions_test",
)


@pytest.fixture
async def pg_db():
    """Real PostgreSQL session — drops and recreates all tables per test."""
    engine = create_async_engine(_PG_URL, isolation_level="AUTOCOMMIT")

    async with engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)
        await conn.run_sync(metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)

    await engine.dispose()
