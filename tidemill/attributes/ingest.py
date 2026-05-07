"""Attribute-definition upsert + customer_attribute fan-out.

Called from:
- ``tidemill/state.py`` on ``customer.created``/``customer.updated`` events
  (origin = the connector type, e.g. 'stripe', 'lago', 'killbill')
- ``tidemill/attributes/routes.py`` for CSV upload (origin='csv') and REST API
  upserts (origin='api')

Type inference is conservative: booleans and numbers are detected before
timestamps, and anything that doesn't match falls back to string.  First-seen
inference wins — once an attribute_definition exists, its declared type
sticks (CSV upload can override via an explicit POST /api/attributes).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


_ISO_SUFFIXES = ("Z", "+00:00", "-00:00")


def infer_type(value: Any) -> str:
    """Return the Tidemill attribute type for *value*.

    One of ``"boolean"``, ``"number"``, ``"timestamp"``, ``"string"``.
    Booleans are tried before numbers (``True`` coerces to ``1`` and
    would otherwise be typed as number).  Timestamps accept ISO-8601
    strings; anything else with non-digit characters falls back to
    string.
    """
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, datetime):
        return "timestamp"
    if not isinstance(value, str):
        return "string"

    s = value.strip()
    if s.lower() in ("true", "false"):
        return "boolean"
    # Number check — reject empty strings and pure-sign tokens.
    try:
        if s and s not in ("+", "-"):
            float(s)
            return "number"
    except ValueError:
        pass
    # Timestamp check — only flag ISO-8601-ish strings.
    if "T" in s or any(s.endswith(suf) for suf in _ISO_SUFFIXES):
        try:
            datetime.fromisoformat(s.replace("Z", "+00:00"))
            return "timestamp"
        except ValueError:
            pass
    return "string"


def _coerce_typed(value: Any, attr_type: str) -> Any:
    """Coerce a raw value into the Python type matching *attr_type*.

    Returns ``None`` for values that can't be coerced (they're stored as
    NULL in the relevant ``value_*`` column).
    """
    if value is None:
        return None
    if attr_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lower = value.strip().lower()
            if lower == "true":
                return True
            if lower == "false":
                return False
        return None
    if attr_type == "number":
        try:
            f = float(value)
        except (ValueError, TypeError):
            return None
        # Preserve int vs float where the source value is naturally int.
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return f
    if attr_type == "timestamp":
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None
    # string
    return str(value)


_VALUE_COLUMN = {
    "string": "value_string",
    "number": "value_number",
    "boolean": "value_bool",
    "timestamp": "value_timestamp",
}


async def upsert_attribute_definition(
    session: AsyncSession,
    key: str,
    *,
    type: str,
    label: str | None = None,
    source: str = "api",
    description: str | None = None,
) -> dict[str, Any]:
    """Insert or fetch an attribute_definition.

    First write wins for ``type`` — a later call with a different type does
    NOT overwrite (callers that want to re-type must DELETE/recreate).
    ``label`` and ``description`` are updated on every call so users can
    rename an attribute without losing its values.
    """
    if type not in _VALUE_COLUMN:
        raise ValueError(f"Unknown attribute type {type!r}")
    now = datetime.now(UTC)
    result = await session.execute(
        text(
            "INSERT INTO attribute_definition"
            " (key, label, type, source, description, created_at, updated_at)"
            " VALUES (:key, :label, :type, :source, :desc, :now, :now)"
            " ON CONFLICT (key) DO UPDATE SET"
            "  label = COALESCE(EXCLUDED.label, attribute_definition.label),"
            "  description = COALESCE(EXCLUDED.description, attribute_definition.description),"
            "  updated_at = EXCLUDED.updated_at"
            " RETURNING key, label, type, source, description, created_at, updated_at"
        ),
        {
            "key": key,
            "label": label or key,
            "type": type,
            "source": source,
            "desc": description,
            "now": now,
        },
    )
    row = result.mappings().one()
    return dict(row)


async def upsert_customer_attribute(
    session: AsyncSession,
    *,
    source_id: str,
    customer_id: str,
    key: str,
    value: Any,
    attr_type: str,
    origin: str,
) -> None:
    """Upsert a single ``customer_attribute`` row.

    ``value`` is coerced to the Python type matching *attr_type* before
    being assigned to the appropriate typed column; the other three value
    columns are set to NULL in the same statement so a re-type on the
    definition doesn't leave stale data.
    """
    coerced = _coerce_typed(value, attr_type)
    col = _VALUE_COLUMN[attr_type]
    other_cols = [c for c in _VALUE_COLUMN.values() if c != col]

    set_clauses = [f"{col} = EXCLUDED.{col}"]
    set_clauses.extend(f"{c} = NULL" for c in other_cols)
    set_clauses.append("origin = EXCLUDED.origin")
    set_clauses.append("updated_at = EXCLUDED.updated_at")

    now = datetime.now(UTC)
    params: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "src": source_id,
        "cid": customer_id,
        "key": key,
        "origin": origin,
        "now": now,
        "val_string": None,
        "val_number": None,
        "val_bool": None,
        "val_timestamp": None,
    }
    # Only the column matching attr_type gets a value.
    if attr_type == "string":
        params["val_string"] = coerced
    elif attr_type == "number":
        params["val_number"] = coerced
    elif attr_type == "boolean":
        params["val_bool"] = coerced
    elif attr_type == "timestamp":
        params["val_timestamp"] = coerced

    await session.execute(
        text(
            "INSERT INTO customer_attribute"
            " (id, source_id, customer_id, key,"
            "  value_string, value_number, value_bool, value_timestamp,"
            "  origin, updated_at)"
            " VALUES (:id, :src, :cid, :key,"
            "  :val_string, :val_number, :val_bool, :val_timestamp,"
            "  :origin, :now)"
            " ON CONFLICT ON CONSTRAINT uq_customer_attr_source_cust_key DO UPDATE SET "
            + ", ".join(set_clauses)
        ),
        params,
    )


async def _existing_values(
    session: AsyncSession,
    source_id: str,
    customer_id: str,
) -> dict[str, tuple[str, Any]]:
    """Return {key: (type, python_value)} for existing rows."""
    result = await session.execute(
        text(
            "SELECT ca.key, ad.type,"
            "  ca.value_string, ca.value_number, ca.value_bool, ca.value_timestamp"
            " FROM customer_attribute ca"
            " JOIN attribute_definition ad ON ad.key = ca.key"
            " WHERE ca.source_id = :src AND ca.customer_id = :cid"
        ),
        {"src": source_id, "cid": customer_id},
    )
    out: dict[str, tuple[str, Any]] = {}
    for r in result.mappings().all():
        t = r["type"]
        v = (
            r["value_string"]
            if t == "string"
            else r["value_number"]
            if t == "number"
            else r["value_bool"]
            if t == "boolean"
            else r["value_timestamp"]
        )
        out[r["key"]] = (t, v)
    return out


async def fan_out_customer_metadata(
    session: AsyncSession,
    *,
    source_id: str,
    customer_id: str,
    metadata: dict[str, Any],
    origin: str,
) -> int:
    """Fan a customer's metadata dict into ``customer_attribute`` rows.

    - Creates ``attribute_definition`` rows for newly-seen keys (type
      inferred from the first value observed).
    - Upserts ``customer_attribute`` rows only for keys that are new or
      changed vs. what's already stored — avoids write amplification when
      a webhook replays unchanged metadata.
    - Does NOT delete rows for keys absent from *metadata*; webhooks may
      send partial updates and we don't want to lose history from an
      accidental ``customer.updated`` with empty metadata.

    *origin* names the writer (``'stripe'``, ``'lago'``, ``'csv'``,
    ``'api'``, …) — used as the attribute-definition source on first
    sight and recorded on every value upsert.

    Returns the number of rows upserted.
    """
    if not metadata:
        return 0

    existing = await _existing_values(session, source_id, customer_id)
    upserted = 0
    for key, raw_value in metadata.items():
        if raw_value is None:
            continue
        # Determine the attribute's type — prefer the existing definition's
        # type if any (first-seen-wins), else infer from this value.
        declared_type: str | None = None
        if key in existing:
            declared_type = existing[key][0]
        else:
            declared_type = infer_type(raw_value)
            await upsert_attribute_definition(
                session,
                key=key,
                type=declared_type,
                label=key,
                source=origin,
                description=None,
            )

        coerced = _coerce_typed(raw_value, declared_type)
        # Skip writes where the stored value already matches — diff keeps
        # this helper idempotent under webhook replays.
        if key in existing and existing[key][1] == coerced:
            continue

        await upsert_customer_attribute(
            session,
            source_id=source_id,
            customer_id=customer_id,
            key=key,
            value=raw_value,
            attr_type=declared_type,
            origin=origin,
        )
        upserted += 1
    return upserted
