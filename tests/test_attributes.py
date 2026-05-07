"""Tests for customer attribute ingestion (SQLite-backed)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from tidemill.attributes.ingest import (
    fan_out_customer_metadata,
    infer_type,
    upsert_attribute_definition,
    upsert_customer_attribute,
)
from tidemill.attributes.registry import (
    distinct_values,
    get_attribute_types,
    list_definitions,
)


class TestInferType:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (True, "boolean"),
            (False, "boolean"),
            ("true", "boolean"),
            ("false", "boolean"),
            ("TRUE", "boolean"),
            (42, "number"),
            (3.14, "number"),
            ("42", "number"),
            ("-1.5", "number"),
            ("2026-01-15T10:00:00Z", "timestamp"),
            ("2026-01-15T10:00:00+00:00", "timestamp"),
            ("hello", "string"),
            ("", "string"),
            ("+", "string"),
            (datetime.now(UTC), "timestamp"),
        ],
    )
    def test_various_values(self, value, expected):
        assert infer_type(value) == expected


# ── DB-backed ingest tests ──────────────────────────────────────────────


async def _ensure_customer(db, source_id: str, customer_id: str) -> None:
    """Minimal connector_source + customer setup for the ingest tests.

    Both inserts use ON CONFLICT DO NOTHING so the helper is idempotent
    across multiple customers within the same test.
    """
    now = datetime.now(UTC)
    await db.execute(
        text(
            "INSERT INTO connector_source (id, type, name, created_at)"
            " VALUES (:id, 'test', 'Test', :now)"
            " ON CONFLICT (id) DO NOTHING"
        ),
        {"id": source_id, "now": now},
    )
    await db.execute(
        text(
            "INSERT INTO customer (id, source_id, external_id, created_at)"
            " VALUES (:cid, :src, :ext, :now)"
            " ON CONFLICT (id) DO NOTHING"
        ),
        {"cid": customer_id, "src": source_id, "ext": f"ext_{customer_id}", "now": now},
    )


class TestUpsertDefinition:
    @pytest.mark.asyncio
    async def test_first_write_wins_on_type(self, db):
        await upsert_attribute_definition(db, key="tier", type="string", label="Tier")
        types = await get_attribute_types(db)
        assert types == {"tier": "string"}

        # Second call with a different type is blocked at the application
        # layer (type column is not in the ON CONFLICT update list).
        await upsert_attribute_definition(db, key="tier", type="number", label="Tier v2")
        types = await get_attribute_types(db)
        assert types == {"tier": "string"}  # unchanged

    @pytest.mark.asyncio
    async def test_label_and_description_update_on_repeat(self, db):
        await upsert_attribute_definition(
            db, key="tier", type="string", label="Old", description="old desc"
        )
        await upsert_attribute_definition(
            db, key="tier", type="string", label="New", description="new desc"
        )
        rows = await list_definitions(db)
        assert len(rows) == 1
        assert rows[0]["label"] == "New"
        assert rows[0]["description"] == "new desc"


class TestUpsertCustomerAttribute:
    @pytest.mark.asyncio
    async def test_writes_typed_column_only(self, db):
        await _ensure_customer(db, "src_1", "cus_a")
        await upsert_attribute_definition(db, key="seats", type="number", label="Seats")
        await upsert_customer_attribute(
            db,
            source_id="src_1",
            customer_id="cus_a",
            key="seats",
            value="42",
            attr_type="number",
            origin="api",
        )
        row = (
            (
                await db.execute(
                    text(
                        "SELECT value_string, value_number, value_bool, value_timestamp"
                        " FROM customer_attribute WHERE customer_id = 'cus_a'"
                    )
                )
            )
            .mappings()
            .one()
        )
        assert row["value_string"] is None
        assert row["value_number"] == 42
        assert row["value_bool"] is None
        assert row["value_timestamp"] is None


class TestFanOut:
    @pytest.mark.asyncio
    async def test_creates_definitions_on_first_sight(self, db):
        await _ensure_customer(db, "src_1", "cus_a")
        count = await fan_out_customer_metadata(
            db,
            source_id="src_1",
            customer_id="cus_a",
            metadata={"tier": "enterprise", "seats": "42", "active": "true"},
            origin="stripe",
        )
        assert count == 3

        types = await get_attribute_types(db)
        assert types == {"tier": "string", "seats": "number", "active": "boolean"}

    @pytest.mark.asyncio
    async def test_diff_skips_unchanged(self, db):
        await _ensure_customer(db, "src_1", "cus_a")
        # First fan-out
        c1 = await fan_out_customer_metadata(
            db,
            source_id="src_1",
            customer_id="cus_a",
            metadata={"tier": "enterprise"},
            origin="stripe",
        )
        # Second fan-out with same value → no writes
        c2 = await fan_out_customer_metadata(
            db,
            source_id="src_1",
            customer_id="cus_a",
            metadata={"tier": "enterprise"},
            origin="stripe",
        )
        assert c1 == 1
        assert c2 == 0

    @pytest.mark.asyncio
    async def test_absent_keys_are_not_deleted(self, db):
        """Partial metadata updates must not wipe existing keys."""
        await _ensure_customer(db, "src_1", "cus_a")
        await fan_out_customer_metadata(
            db,
            source_id="src_1",
            customer_id="cus_a",
            metadata={"tier": "enterprise", "account_manager": "Alice"},
            origin="stripe",
        )
        await fan_out_customer_metadata(
            db,
            source_id="src_1",
            customer_id="cus_a",
            metadata={"tier": "plus"},  # account_manager absent
            origin="stripe",
        )
        rows = (
            (
                await db.execute(
                    text(
                        "SELECT key FROM customer_attribute WHERE customer_id = 'cus_a'"
                        " ORDER BY key"
                    )
                )
            )
            .mappings()
            .all()
        )
        assert [r["key"] for r in rows] == ["account_manager", "tier"]


class TestDistinctValues:
    @pytest.mark.asyncio
    async def test_returns_distinct(self, db):
        await _ensure_customer(db, "src_1", "cus_a")
        await _ensure_customer(db, "src_1", "cus_b")
        await upsert_attribute_definition(db, key="tier", type="string")
        for cid, val in [("cus_a", "enterprise"), ("cus_b", "plus"), ("cus_a", "enterprise")]:
            await upsert_customer_attribute(
                db,
                source_id="src_1",
                customer_id=cid,
                key="tier",
                value=val,
                attr_type="string",
                origin="api",
            )
        vals = await distinct_values(db, "tier")
        assert sorted(vals) == ["enterprise", "plus"]

    @pytest.mark.asyncio
    async def test_unknown_key_returns_empty(self, db):
        assert await distinct_values(db, "nope") == []
