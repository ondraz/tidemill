"""Worker startup hardening.

The connector_source bootstrap must tolerate the cold-start race where the
worker runs before the API has created the schema (SQLSTATE 42P01,
"undefined_table").
"""

from __future__ import annotations

import contextlib

import pytest
from sqlalchemy.exc import ProgrammingError

from tidemill import worker


class _FakeOrig:
    """Stand-in for asyncpg's error object, which carries .sqlstate."""

    def __init__(self, sqlstate: str | None) -> None:
        self.sqlstate = sqlstate


def _programming_error(message: str, sqlstate: str | None) -> ProgrammingError:
    return ProgrammingError(message, None, _FakeOrig(sqlstate))


class _FakeEngine:
    """Minimal engine whose begin() yields a no-op connection context."""

    @contextlib.asynccontextmanager
    async def _begin(self):
        yield object()

    def begin(self):
        return self._begin()


def test_is_missing_table_detects_sqlstate() -> None:
    assert worker._is_missing_table(_programming_error("boom", "42P01")) is True


def test_is_missing_table_detects_message_fallback() -> None:
    # asyncpg's adapter may not expose .sqlstate; the rendered message still
    # embeds "does not exist".
    exc = _programming_error('relation "connector_source" does not exist', None)
    assert worker._is_missing_table(exc) is True


def test_is_missing_table_ignores_other_errors() -> None:
    assert worker._is_missing_table(_programming_error("syntax error", "42601")) is False


async def test_bootstrap_retries_until_schema_ready(monkeypatch) -> None:
    calls = 0

    async def fake_ensure(_conn) -> None:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise _programming_error('relation "connector_source" does not exist', "42P01")

    monkeypatch.setattr("tidemill.bootstrap.ensure_connector_sources", fake_ensure)

    await worker._bootstrap_connector_sources(_FakeEngine(), attempts=5, delay=0)

    assert calls == 3


async def test_bootstrap_reraises_non_missing_table(monkeypatch) -> None:
    async def fake_ensure(_conn) -> None:
        raise _programming_error("undefined_column", "42703")

    monkeypatch.setattr("tidemill.bootstrap.ensure_connector_sources", fake_ensure)

    with pytest.raises(ProgrammingError):
        await worker._bootstrap_connector_sources(_FakeEngine(), attempts=5, delay=0)


async def test_bootstrap_gives_up_after_attempts(monkeypatch) -> None:
    calls = 0

    async def fake_ensure(_conn) -> None:
        nonlocal calls
        calls += 1
        raise _programming_error('relation "connector_source" does not exist', "42P01")

    monkeypatch.setattr("tidemill.bootstrap.ensure_connector_sources", fake_ensure)

    with pytest.raises(ProgrammingError):
        await worker._bootstrap_connector_sources(_FakeEngine(), attempts=3, delay=0)

    assert calls == 3
