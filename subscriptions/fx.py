"""Foreign exchange rate conversion."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession


async def to_base_cents(
    amount_cents: int,
    currency: str,
    on_date: date,
    db: AsyncSession,
    base_currency: str = "USD",
) -> int:
    """Convert *amount_cents* to *base_currency* using the fx_rate table.

    Same-currency is a passthrough (no DB query).
    """
    if currency.upper() == base_currency.upper():
        return amount_cents

    result = await db.execute(
        text(
            "SELECT rate FROM fx_rate"
            " WHERE from_currency = :c AND to_currency = :base"
            " AND date <= :d ORDER BY date DESC LIMIT 1"
        ),
        {"c": currency.upper(), "base": base_currency.upper(), "d": on_date},
    )
    rate = result.scalar()
    if rate is None:
        raise ValueError(f"No FX rate for {currency}/{base_currency} on or before {on_date}")
    return int(amount_cents * rate)
