"""Tests for ExpensesMetric — query methods over bill/expense tables.

The expenses metric uses raw SQL against the platform-neutral schema, so
these tests insert rows directly into ``bill``/``bill_line``/``expense``/
``expense_line``/``account``/``vendor`` and verify aggregates.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text

from tidemill.metrics.expenses.metric import ExpensesMetric

from .conftest import SRC


async def _seed_minimal_books(db) -> None:
    """Insert a minimal expense fixture set into the test DB.

    Creates two vendors, three accounts, a bill with two lines, a paid bill,
    and a direct expense (purchase) — just enough to exercise the aggregation
    paths in every query method.
    """
    # Source row first (FK target).
    await db.execute(
        text(
            "INSERT INTO connector_source (id, type, name, created_at)"
            " VALUES (:id, 'quickbooks', 'QBO Test', :now)"
        ),
        {"id": SRC, "now": datetime.now(UTC)},
    )
    await db.execute(
        text(
            "INSERT INTO vendor (id, source_id, external_id, name,"
            "  currency, active, created_at)"
            " VALUES ('v1', :src, 'v_aws', 'AWS', 'USD', 1, :now),"
            "        ('v2', :src, 'v_hetz', 'Hetzner', 'EUR', 1, :now)"
        ),
        {"src": SRC, "now": datetime.now(UTC)},
    )
    await db.execute(
        text(
            "INSERT INTO account (id, source_id, external_id, name,"
            "  account_type, active, created_at)"
            " VALUES ('a1', :src, 'a_host',  'Hosting',  'expense', 1, :now),"
            "        ('a2', :src, 'a_swsub', 'Software', 'expense', 1, :now),"
            "        ('a3', :src, 'a_cogs',  'COGS',     'cogs',    1, :now)"
        ),
        {"src": SRC, "now": datetime.now(UTC)},
    )
    # Open bill: two lines, one Hosting + one Software.
    await db.execute(
        text(
            "INSERT INTO bill (id, source_id, external_id, vendor_id, status,"
            "  currency, total_cents, total_base_cents, txn_date, created_at)"
            " VALUES ('b1', :src, 'b_001', 'v1', 'open',"
            "  'USD', 500000, 500000, :d, :now)"
        ),
        {"src": SRC, "d": datetime(2026, 1, 15, tzinfo=UTC), "now": datetime.now(UTC)},
    )
    await db.execute(
        text(
            "INSERT INTO bill_line (id, bill_id, account_id, amount_cents,"
            "  amount_base_cents, currency)"
            " VALUES ('bl1', 'b1', 'a1', 420000, 420000, 'USD'),"
            "        ('bl2', 'b1', 'a2',  80000,  80000, 'USD')"
        ),
    )
    # Paid bill at Hetzner — different month.
    await db.execute(
        text(
            "INSERT INTO bill (id, source_id, external_id, vendor_id, status,"
            "  currency, total_cents, total_base_cents, txn_date, paid_at,"
            "  created_at)"
            " VALUES ('b2', :src, 'b_002', 'v2', 'paid',"
            "  'EUR', 18000, 19500, :d, :paid, :now)"
        ),
        {
            "src": SRC,
            "d": datetime(2026, 2, 8, tzinfo=UTC),
            "paid": datetime(2026, 2, 28, tzinfo=UTC),
            "now": datetime.now(UTC),
        },
    )
    await db.execute(
        text(
            "INSERT INTO bill_line (id, bill_id, account_id, amount_cents,"
            "  amount_base_cents, currency)"
            " VALUES ('bl3', 'b2', 'a1', 18000, 19500, 'EUR')"
        ),
    )
    # Direct expense (no bill): a marketing-style purchase routed to COGS.
    await db.execute(
        text(
            "INSERT INTO expense (id, source_id, external_id, vendor_id,"
            "  payment_type, currency, total_cents, total_base_cents,"
            "  txn_date, created_at)"
            " VALUES ('e1', :src, 'e_001', 'v1', 'credit_card',"
            "  'USD', 32000, 32000, :d, :now)"
        ),
        {"src": SRC, "d": datetime(2026, 2, 10, tzinfo=UTC), "now": datetime.now(UTC)},
    )
    await db.execute(
        text(
            "INSERT INTO expense_line (id, expense_id, account_id,"
            "  amount_cents, amount_base_cents, currency)"
            " VALUES ('el1', 'e1', 'a3', 32000, 32000, 'USD')"
        ),
    )
    await db.commit()


@pytest.fixture
async def metric(db) -> ExpensesMetric:
    await _seed_minimal_books(db)
    m = ExpensesMetric()
    m.init(db=db)
    return m


class TestExpensesTotal:
    @pytest.mark.asyncio
    async def test_full_window_sums_everything(self, metric):
        # Bill1: 500_000, Bill2: 19_500 (base), Expense1: 32_000 → 551_500
        result = await metric.query(
            {"query_type": "total", "start": date(2026, 1, 1), "end": date(2026, 12, 31)}
        )
        assert result["total_base_cents"] == 551_500
        assert result["line_count"] == 4

    @pytest.mark.asyncio
    async def test_january_only(self, metric):
        result = await metric.query(
            {"query_type": "total", "start": date(2026, 1, 1), "end": date(2026, 1, 31)}
        )
        # Only Bill1's two lines fall in January.
        assert result["total_base_cents"] == 500_000
        assert result["line_count"] == 2


class TestExpensesByAccountType:
    @pytest.mark.asyncio
    async def test_groups_by_normalized_account_type(self, metric):
        rows = await metric.query(
            {
                "query_type": "by_account_type",
                "start": date(2026, 1, 1),
                "end": date(2026, 12, 31),
            }
        )
        by_type = {r["account_type"]: r["amount_base_cents"] for r in rows}
        # Hosting + Software lines + Hetzner Hosting line = 519_500 expense
        # COGS line: 32_000
        assert by_type["expense"] == 519_500
        assert by_type["cogs"] == 32_000


class TestExpensesByVendor:
    @pytest.mark.asyncio
    async def test_groups_by_vendor(self, metric):
        rows = await metric.query(
            {
                "query_type": "by_vendor",
                "start": date(2026, 1, 1),
                "end": date(2026, 12, 31),
            }
        )
        by_vendor = {r["vendor_name"]: r["amount_base_cents"] for r in rows}
        # AWS: Bill1 lines (500_000) + Expense1 (32_000) = 532_000
        # Hetzner: Bill2 (19_500)
        assert by_vendor["AWS"] == 532_000
        assert by_vendor["Hetzner"] == 19_500


class TestVoidedExclusion:
    """Voided bills/expenses must drop out of every aggregate."""

    @pytest.mark.asyncio
    async def test_voided_bill_excluded_from_total(self, metric, db):
        await db.execute(
            text("UPDATE bill SET voided_at = :v WHERE id = 'b1'"),
            {"v": datetime(2026, 1, 31, tzinfo=UTC)},
        )
        await db.commit()
        result = await metric.query(
            {"query_type": "total", "start": date(2026, 1, 1), "end": date(2026, 12, 31)}
        )
        # Bill1 (500_000) is voided; only Bill2 (19_500) + Expense1 (32_000) remain.
        assert result["total_base_cents"] == 51_500
