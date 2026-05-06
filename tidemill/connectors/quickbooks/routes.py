"""QuickBooks Online webhook + OAuth endpoints."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Header, Query, Request, Response
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks", "connectors"])


@router.post("/webhooks/quickbooks")
async def receive_quickbooks_webhook(
    request: Request,
    intuit_signature: str | None = Header(None, alias="intuit-signature"),
) -> Response:
    """Receive a QBO webhook notification.

    The notification payload only carries entity IDs; we fetch each full
    entity from the QBO API before publishing events.
    """
    from tidemill.api.app import app as fastapi_app
    from tidemill.connectors import get_connector

    body = await request.body()
    payload = await request.json()

    source_id = request.query_params.get("source_id", "quickbooks")
    config = await _load_source_config(fastapi_app, source_id)

    connector = get_connector("quickbooks", source_id=source_id, config=config)

    if intuit_signature and not connector.verify_signature(body, intuit_signature):
        return Response(status_code=400, content="Invalid signature")

    events = await connector.fetch_and_translate(payload)  # type: ignore[attr-defined]
    if events:
        producer = fastapi_app.state.producer
        await producer.publish_many(events)

    return Response(status_code=200, content="ok")


# ── OAuth 2.0 flow ───────────────────────────────────────────────────────


@router.get("/connectors/quickbooks/oauth/start")
async def oauth_start() -> RedirectResponse:
    """Redirect the browser to Intuit's authorization page.

    Scopes:
      - ``com.intuit.quickbooks.accounting`` is required to read Bills,
        Vendors, Accounts, Purchases, BillPayments.
    """
    import os
    import secrets
    from urllib.parse import urlencode

    client_id = os.environ.get("QUICKBOOKS_CLIENT_ID", "")
    redirect_uri = os.environ.get("QUICKBOOKS_REDIRECT_URI", "")
    if not client_id or not redirect_uri:
        return RedirectResponse(
            "/?error=quickbooks_oauth_not_configured", status_code=302
        )
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "com.intuit.quickbooks.accounting",
        "state": state,
    }
    url = "https://appcenter.intuit.com/connect/oauth2?" + urlencode(params)
    return RedirectResponse(url, status_code=302)


@router.get("/connectors/quickbooks/oauth/callback")
async def oauth_callback(
    code: str = Query(...),
    realmId: str = Query(...),  # noqa: N803 — Intuit param name
    state: str | None = Query(None),
) -> Response:
    """Exchange the authorization code for tokens and persist them.

    Each QBO realm gets its own ``connector_source`` row so the standard
    ``(source_id, external_id)`` uniqueness keeps multi-realm setups clean.
    The ``source_id`` we use is ``quickbooks-{realmId}``.
    """
    import os
    from datetime import timedelta

    import httpx
    from sqlalchemy import text

    from tidemill.api.app import app as fastapi_app

    client_id = os.environ.get("QUICKBOOKS_CLIENT_ID", "")
    client_secret = os.environ.get("QUICKBOOKS_CLIENT_SECRET", "")
    redirect_uri = os.environ.get("QUICKBOOKS_REDIRECT_URI", "")
    environment = os.environ.get("QUICKBOOKS_ENVIRONMENT", "production")

    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.post(
            "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
            auth=(client_id, client_secret),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
    if resp.status_code != 200:
        return Response(
            status_code=400,
            content=f"Token exchange failed: {resp.status_code} {resp.text}",
        )
    body = resp.json()
    expires_at = datetime.now(UTC) + timedelta(seconds=int(body.get("expires_in", 3600)))
    config = {
        "client_id": client_id,
        "client_secret": client_secret,
        "webhook_verifier_token": os.environ.get("QUICKBOOKS_WEBHOOK_VERIFIER_TOKEN", ""),
        "environment": environment,
        "realm_id": realmId,
        "access_token": body["access_token"],
        "refresh_token": body["refresh_token"],
        "access_token_expires_at": expires_at.isoformat(),
    }

    source_id = f"quickbooks-{realmId}"
    factory = fastapi_app.state.session_factory
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO connector_source (id, type, name, config, created_at)"
                " VALUES (:id, 'quickbooks', :name, :cfg, :now)"
                " ON CONFLICT (id) DO UPDATE SET config = EXCLUDED.config"
            ),
            {
                "id": source_id,
                "name": f"QuickBooks ({realmId})",
                "cfg": json.dumps(config),
                "now": datetime.now(UTC),
            },
        )
        await session.commit()

    logger.info("quickbooks oauth complete realm=%s source_id=%s", realmId, source_id)
    return RedirectResponse(f"/?quickbooks_connected={source_id}", status_code=302)


# ── helpers ──────────────────────────────────────────────────────────────


async def _load_source_config(app, source_id: str) -> dict:  # type: ignore[no-untyped-def]
    """Read ``connector_source.config`` JSON for *source_id*.

    Falls back to the static env-var config in ``app.state.connector_configs``
    so a developer who hasn't yet completed the OAuth dance can still see
    the route handlers respond.
    """
    from sqlalchemy import text

    factory = getattr(app.state, "session_factory", None)
    fallback = getattr(app.state, "connector_configs", {}).get("quickbooks", {})
    if factory is None:
        return fallback
    async with factory() as session:
        result = await session.execute(
            text("SELECT config FROM connector_source WHERE id = :id"),
            {"id": source_id},
        )
        row = result.mappings().first()
    if row and row["config"]:
        try:
            return {**fallback, **json.loads(row["config"])}
        except json.JSONDecodeError:
            logger.warning("connector_source.config not JSON for %s", source_id)
    return fallback
