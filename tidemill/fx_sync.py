"""Populate the ``fx_rate`` table from a public ECB feed (Frankfurter).

Why this exists: ``to_base_cents`` raises ``FxRateMissingError`` whenever a
metric handler converts a non-base-currency amount on a date that has no
matching ``fx_rate`` row. Without a regular sync, every non-USD subscriber
event dead-letters. This module fetches missing days on startup and on a
recurring schedule so the converter always has a row to read.

Source: https://api.frankfurter.dev — daily ECB reference rates, no key
required, supports ``{start}..{end}`` time-series queries.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import text

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

FRANKFURTER_URL = "https://api.frankfurter.dev/v1"
SOURCE_NAME = "frankfurter"

# Currencies seeded into the test stack even before any subscriptions exist.
# Keeps `seed.sh` working from a cold start (no ingested data yet). Override
# via the ``TIDEMILL_FX_CURRENCIES`` env var (comma-separated ISO 4217 codes,
# e.g. ``USD,EUR,GBP,SEK``).
DEFAULT_SEED_CURRENCIES = ("USD", "EUR", "GBP", "CAD", "AUD", "JPY")


def _configured_currencies() -> tuple[str, ...]:
    """Currencies to sync when the caller doesn't pass an explicit list.

    Reads ``TIDEMILL_FX_CURRENCIES`` (comma-separated) and falls back to
    :data:`DEFAULT_SEED_CURRENCIES`. Whitespace and empty entries are
    ignored so the same env var format works in shells and ``.env`` files.
    """
    raw = os.environ.get("TIDEMILL_FX_CURRENCIES", "")
    parsed = tuple(c.strip().upper() for c in raw.split(",") if c.strip())
    return parsed or DEFAULT_SEED_CURRENCIES


# Default lookback for the very first sync — enough history for the seed
# script's 18-month window plus headroom.
DEFAULT_LOOKBACK_DAYS = 730

# Default cadence for the background refresher.
DEFAULT_REFRESH_INTERVAL_S = 12 * 3600


def _base_currency() -> str:
    return os.environ.get("BASE_CURRENCY", "USD").upper()


# ── DB helpers ───────────────────────────────────────────────────────────


async def detect_currencies(db: AsyncSession) -> set[str]:
    """Return distinct non-base currencies present in entity tables.

    Reads ``subscription`` / ``invoice`` / ``payment`` because those are
    the columns metric handlers feed into ``to_base_cents``. Empty result
    is fine — callers union with ``DEFAULT_SEED_CURRENCIES`` so a fresh
    DB still gets common pairs synced.
    """
    base = _base_currency()
    result = await db.execute(
        text(
            "SELECT DISTINCT UPPER(currency) AS c FROM ("
            "  SELECT currency FROM subscription WHERE currency IS NOT NULL"
            "  UNION ALL"
            "  SELECT currency FROM invoice WHERE currency IS NOT NULL"
            "  UNION ALL"
            "  SELECT currency FROM payment WHERE currency IS NOT NULL"
            ") t WHERE currency IS NOT NULL"
        )
    )
    return {row.c for row in result if row.c and row.c != base}


async def _last_synced_date(db: AsyncSession, currency: str, base: str) -> date | None:
    result = await db.execute(
        text("SELECT MAX(date) FROM fx_rate WHERE from_currency = :c AND to_currency = :b"),
        {"c": currency, "b": base},
    )
    return result.scalar()


async def _upsert_rates(
    db: AsyncSession,
    currency: str,
    base: str,
    rates: Iterable[tuple[date, Decimal]],
) -> int:
    """Idempotent upsert. Returns the number of (currency, date) pairs written."""
    n = 0
    for d, rate in rates:
        await db.execute(
            text(
                "INSERT INTO fx_rate"
                " (id, date, from_currency, to_currency, rate, source)"
                " VALUES (:id, :d, :c, :b, :r, :s)"
                " ON CONFLICT ON CONSTRAINT uq_fx_rate DO UPDATE SET"
                "  rate = EXCLUDED.rate,"
                "  source = EXCLUDED.source"
            ),
            {
                "id": str(uuid.uuid4()),
                "d": d,
                "c": currency,
                "b": base,
                "r": rate,
                "s": SOURCE_NAME,
            },
        )
        n += 1
    return n


# ── Frankfurter fetch ────────────────────────────────────────────────────


async def _fetch_timeseries(
    client: httpx.AsyncClient,
    base: str,
    symbols: list[str],
    since: date,
    until: date,
) -> dict[date, dict[str, Decimal]]:
    """Fetch ``base → {symbol: rate}`` time-series from Frankfurter.

    Returns ``{date: {symbol: rate}}`` where ``rate`` means *1 base = rate symbol*.
    Frankfurter returns rates only for trading days, so weekends / holidays
    are absent from the response — the converter handles this by selecting
    the most recent row on or before the target date.
    """
    if not symbols:
        return {}
    if since > until:
        return {}
    url = f"{FRANKFURTER_URL}/{since.isoformat()}..{until.isoformat()}"
    params = {"base": base, "symbols": ",".join(symbols)}
    resp = await client.get(url, params=params, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    out: dict[date, dict[str, Decimal]] = {}
    for date_str, rates_for_day in (data.get("rates") or {}).items():
        d = date.fromisoformat(date_str)
        out[d] = {sym.upper(): Decimal(str(r)) for sym, r in rates_for_day.items()}
    return out


# ── public entry points ──────────────────────────────────────────────────


async def sync_fx_rates(
    db: AsyncSession,
    *,
    since: date | None = None,
    until: date | None = None,
    base: str | None = None,
    currencies: Iterable[str] | None = None,
) -> int:
    """Fetch missing FX rates and upsert into ``fx_rate``.

    ``since`` defaults to the day after the most recent stored rate (or
    ``today - DEFAULT_LOOKBACK_DAYS`` if the table is empty). ``until``
    defaults to today. ``currencies`` defaults to the union of detected
    currencies (subscription/invoice/payment) and ``DEFAULT_SEED_CURRENCIES``.

    Returns the total number of (currency, date) rows written.
    """
    base = (base or _base_currency()).upper()
    until = until or datetime.now(UTC).date()

    if currencies is None:
        detected = await detect_currencies(db)
        currencies = detected | set(_configured_currencies())
    targets = sorted({c.upper() for c in currencies if c.upper() != base})
    if not targets:
        return 0

    # Per-currency lower bound — pull each currency forward from its own
    # last-synced day so a newly-added currency doesn't wait for the others'
    # next refresh window.
    explicit_since = since
    total_written = 0
    async with httpx.AsyncClient() as client:
        # Group currencies that need the same start date so we minimize
        # HTTP calls — typical case is one bucket per refresh tick.
        buckets: dict[date, list[str]] = {}
        for c in targets:
            if explicit_since is not None:
                start = explicit_since
            else:
                last = await _last_synced_date(db, c, base)
                start = (
                    last + timedelta(days=1)
                    if last is not None
                    else until - timedelta(days=DEFAULT_LOOKBACK_DAYS)
                )
            if start > until:
                continue
            buckets.setdefault(start, []).append(c)

        for start, syms in buckets.items():
            try:
                ts = await _fetch_timeseries(client, base, syms, start, until)
            except httpx.HTTPError, ValueError:
                logger.exception(
                    "fx_sync: Frankfurter fetch failed (base=%s, symbols=%s, %s..%s)",
                    base,
                    syms,
                    start,
                    until,
                )
                continue

            # Frankfurter returns BASE→C; we store C→BASE. Invert per row.
            for d, rates_for_day in ts.items():
                pairs = []
                for sym, base_to_sym in rates_for_day.items():
                    if base_to_sym == 0:
                        continue
                    pairs.append((d, sym, Decimal(1) / base_to_sym))
                # Group by symbol so each upsert run is one currency.
                for d_val, sym, inv_rate in pairs:
                    written = await _upsert_rates(db, sym, base, [(d_val, inv_rate)])
                    total_written += written

    if total_written:
        logger.info(
            "fx_sync: wrote %d fx_rate rows (base=%s, currencies=%s)",
            total_written,
            base,
            targets,
        )
    return total_written


async def run_periodic_fx_sync(
    factory: async_sessionmaker[AsyncSession],
    *,
    interval_s: float = DEFAULT_REFRESH_INTERVAL_S,
    stop: asyncio.Event | None = None,
) -> None:
    """Background task: refresh fx_rate every ``interval_s`` seconds.

    First tick runs immediately so callers don't need to invoke ``sync_fx_rates``
    separately on startup. The loop catches all exceptions per-iteration so a
    transient Frankfurter outage doesn't kill the task.
    """
    stop = stop or asyncio.Event()
    while not stop.is_set():
        try:
            async with factory() as session:
                await sync_fx_rates(session)
                await session.commit()
        except Exception:
            logger.exception("fx_sync: periodic refresh failed")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
