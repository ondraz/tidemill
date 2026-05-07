"""Minimal async HTTP client for the QuickBooks Online REST API.

Handles:
  - OAuth 2.0 token refresh (access tokens expire in ~1 hour)
  - Sandbox vs production base URLs
  - Pagination of the Query endpoint
  - Single-entity GETs for webhook fetch-and-translate

Tokens are read from ``config`` and persisted back via ``_persist_tokens``,
which writes the refreshed ``config`` into ``connector_source.config`` so
subsequent requests reuse the new access token.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

_PRODUCTION_BASE = "https://quickbooks.api.intuit.com/v3/company"
_SANDBOX_BASE = "https://sandbox-quickbooks.api.intuit.com/v3/company"

# Page size for the QBO Query API. 1000 is the maximum.
_QBO_PAGE_SIZE = 1000


class QuickBooksAPIError(RuntimeError):
    """Raised when a QBO REST call returns a non-2xx response."""


class QuickBooksClient:
    """Thin wrapper around httpx for QBO REST calls.

    A new client is constructed per request/backfill and ``close()`` is
    called when done. Refresh-on-401 is implemented in :meth:`_request`.
    """

    def __init__(self, config: dict[str, Any], *, source_id: str) -> None:
        self.config = config
        self.source_id = source_id
        self._http = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        await self._http.aclose()

    @property
    def _base_url(self) -> str:
        env = self.config.get("environment", "production")
        return _SANDBOX_BASE if env == "sandbox" else _PRODUCTION_BASE

    # ── auth ─────────────────────────────────────────────────────────────

    async def _ensure_access_token(self) -> str:
        """Return a valid access token, refreshing if expired."""
        access = self.config.get("access_token")
        expires_at = self.config.get("access_token_expires_at")
        # Refresh if no access token or it expires within the next 60s.
        if access and expires_at:
            try:
                expiry = datetime.fromisoformat(expires_at)
            except ValueError:
                expiry = datetime.now(UTC) - timedelta(seconds=1)
            # Manually-provisioned configs may store a naive ISO timestamp;
            # treat naive values as UTC so the comparison below doesn't
            # raise TypeError and crash every QBO API call.
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            if expiry > datetime.now(UTC) + timedelta(seconds=60):
                return str(access)
        return await self._refresh()

    async def _refresh(self) -> str:
        refresh_token = self.config.get("refresh_token")
        client_id = self.config.get("client_id")
        client_secret = self.config.get("client_secret")
        if not (refresh_token and client_id and client_secret):
            raise QuickBooksAPIError(
                "QuickBooks config missing refresh_token/client_id/client_secret —"
                " complete the OAuth flow first."
            )
        resp = await self._http.post(
            _TOKEN_URL,
            auth=(client_id, client_secret),
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            raise QuickBooksAPIError(f"Token refresh failed: {resp.status_code} {resp.text}")
        body = resp.json()
        access_token: str = body["access_token"]
        new_refresh = body.get("refresh_token", refresh_token)
        expires_in = int(body.get("expires_in", 3600))
        expiry = datetime.now(UTC) + timedelta(seconds=expires_in)
        self.config["access_token"] = access_token
        self.config["refresh_token"] = new_refresh
        self.config["access_token_expires_at"] = expiry.isoformat()
        await self._persist_tokens()
        return access_token

    # Per-realm dynamic config — these are the only fields the client
    # writes back to ``connector_source.config``. Long-lived secrets
    # (``client_id`` / ``client_secret`` / ``webhook_verifier_token``)
    # stay env-only so a DB compromise doesn't leak them.
    _PERSISTED_FIELDS: tuple[str, ...] = (
        "access_token",
        "refresh_token",
        "access_token_expires_at",
        "realm_id",
        "environment",
    )

    async def _persist_tokens(self) -> None:
        """Update the per-realm token row in ``connector_source.config``.

        Reads the existing JSON, overlays our refreshed token fields, then
        writes back. Best-effort — if no app session is available (unit
        tests, seed scripts), the in-memory config is still updated and
        the next refresh will succeed the same way.
        """
        try:
            from tidemill.api.app import app as fastapi_app

            factory = getattr(fastapi_app.state, "session_factory", None)
            if factory is None:
                return
            from sqlalchemy import text

            updates = {k: self.config[k] for k in self._PERSISTED_FIELDS if k in self.config}
            async with factory() as session:
                existing_row = await session.execute(
                    text("SELECT config FROM connector_source WHERE id = :sid"),
                    {"sid": self.source_id},
                )
                existing_cfg: dict[str, Any] = {}
                row = existing_row.mappings().first()
                if row and row["config"]:
                    try:
                        existing_cfg = json.loads(row["config"])
                    except json.JSONDecodeError:
                        existing_cfg = {}
                # Defensive: strip env-only secrets if a previous version
                # accidentally persisted them, so they get cleaned up over
                # time without a manual migration.
                for env_only in (
                    "client_id",
                    "client_secret",
                    "webhook_verifier_token",
                    "redirect_uri",
                ):
                    existing_cfg.pop(env_only, None)
                existing_cfg.update(updates)
                await session.execute(
                    text("UPDATE connector_source SET config = :cfg WHERE id = :sid"),
                    {"cfg": json.dumps(existing_cfg), "sid": self.source_id},
                )
                await session.commit()
        except Exception:  # pragma: no cover — non-fatal
            logger.debug("token persist skipped (no app session)", exc_info=True)

    # ── HTTP ─────────────────────────────────────────────────────────────

    async def _request(
        self, method: str, url: str, *, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        access = await self._ensure_access_token()
        headers = {"Authorization": f"Bearer {access}", "Accept": "application/json"}
        resp = await self._http.request(method, url, headers=headers, params=params)
        if resp.status_code == 401:
            # Force-refresh and retry once.
            self.config.pop("access_token", None)
            access = await self._refresh()
            headers["Authorization"] = f"Bearer {access}"
            resp = await self._http.request(method, url, headers=headers, params=params)
        if resp.status_code >= 300:
            raise QuickBooksAPIError(f"{method} {url} → {resp.status_code} {resp.text}")
        body: dict[str, Any] = resp.json()
        return body

    # ── public API ───────────────────────────────────────────────────────

    async def get_entity(
        self, realm_id: str, entity_name: str, entity_id: str
    ) -> dict[str, Any] | None:
        """GET /v3/company/{realmId}/{entity}/{id} — fetch a single entity."""
        url = f"{self._base_url}/{realm_id}/{entity_name.lower()}/{entity_id}"
        try:
            body = await self._request("GET", url, params={"minorversion": "65"})
        except QuickBooksAPIError as exc:
            logger.warning("QBO fetch failed for %s/%s: %s", entity_name, entity_id, exc)
            return None
        # QBO wraps single-entity responses as {"Bill": {...}, "time": "..."}.
        return body.get(entity_name)

    async def query_entities(
        self, realm_id: str, entity_name: str, where_clause: str = ""
    ) -> AsyncIterator[dict[str, Any]]:
        """Paginate the Query API: SELECT * FROM <entity_name>.

        QBO's pagination uses STARTPOSITION (1-indexed) + MAXRESULTS.
        ``where_clause`` is appended verbatim (must include the leading
        ``WHERE`` keyword).
        """
        url = f"{self._base_url}/{realm_id}/query"
        start = 1
        while True:
            qbo_query = (
                f"SELECT * FROM {entity_name}{where_clause}"
                f" STARTPOSITION {start} MAXRESULTS {_QBO_PAGE_SIZE}"
            )
            body = await self._request(
                "GET", url, params={"query": qbo_query, "minorversion": "65"}
            )
            response = body.get("QueryResponse") or {}
            objects = response.get(entity_name) or []
            for obj in objects:
                yield obj
            if len(objects) < _QBO_PAGE_SIZE:
                return
            start += _QBO_PAGE_SIZE
