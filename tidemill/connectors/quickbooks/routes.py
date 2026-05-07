"""QuickBooks Online webhook + OAuth endpoints."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

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

    ``source_id`` is derived from the payload's ``realmId`` so a single
    webhook URL works for every connected company. The optional
    ``?source_id=`` query param overrides this for single-realm setups.
    """
    from tidemill.api.app import app as fastapi_app
    from tidemill.connectors import get_connector

    body = await request.body()
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        # Log full details server-side; return a generic message so we
        # don't leak parser internals to the caller (CodeQL: information
        # exposure through an exception).
        logger.warning("quickbooks webhook received invalid JSON", exc_info=True)
        return Response(status_code=400, content="Invalid JSON body")
    if not isinstance(payload, dict):
        return Response(status_code=400, content="JSON body must be an object")

    source_id = request.query_params.get("source_id") or _source_id_from_payload(payload)
    if not source_id:
        return Response(
            status_code=400,
            content="missing source_id (no realmId in payload, no ?source_id= query)",
        )
    config = await _load_source_config(fastapi_app, source_id)

    connector = get_connector("quickbooks", source_id=source_id, config=config)

    # When a verifier token is configured, *require* the signature header —
    # otherwise an attacker could bypass verification by simply omitting it.
    has_verifier = bool(config.get("webhook_verifier_token"))
    if has_verifier and not intuit_signature:
        return Response(status_code=400, content="Missing intuit-signature header")
    if intuit_signature and not connector.verify_signature(body, intuit_signature):
        return Response(status_code=400, content="Invalid signature")

    events = await connector.fetch_and_translate(payload)  # type: ignore[attr-defined]
    if events:
        producer = fastapi_app.state.producer
        await producer.publish_many(events)

    return Response(status_code=200, content="ok")


def _source_id_from_payload(payload: dict[str, Any]) -> str | None:
    """Pick the first realmId out of the QBO notification envelope.

    QBO can batch notifications for multiple realms in one POST in theory,
    but each Intuit Developer app webhook is registered against a single
    realm in practice. We use the first one we see; mismatched realms in
    the same payload will load the wrong config and miss tokens, which is
    safer than silently routing into ``"quickbooks"``.
    """
    for notif in payload.get("eventNotifications", []) or []:
        realm = notif.get("realmId")
        if realm:
            return f"quickbooks-{realm}"
    return None


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
        return RedirectResponse("/?error=quickbooks_oauth_not_configured", status_code=302)
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
        # Log Intuit's full response server-side; the user just sees a
        # generic failure so we don't echo upstream error bodies (which
        # may include token-exchange internals) into a public response.
        logger.warning("quickbooks token exchange failed: %s %s", resp.status_code, resp.text)
        return Response(status_code=400, content="Token exchange failed")
    body = resp.json()
    expires_at = datetime.now(UTC) + timedelta(seconds=int(body.get("expires_in", 3600)))
    # Persist only the per-realm dynamic fields (tokens, realm/environment).
    # client_id / client_secret / webhook_verifier_token are always read
    # from env via app.state.connector_configs, so we never write them to
    # connector_source.config — keeping the durable secret surface env-only.
    persisted = {
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
                "cfg": json.dumps(persisted),
                "now": datetime.now(UTC),
            },
        )
        await session.commit()

    logger.info("quickbooks oauth complete realm=%s source_id=%s", realmId, source_id)
    # Redirect to a static success path — the frontend can fetch the
    # newly-created connector source via the API. Echoing realmId/source_id
    # back into the redirect URL was flagged by CodeQL as untrusted-redirect
    # input even though we control its shape.
    return RedirectResponse("/?quickbooks_connected=1", status_code=302)


# ── helpers ──────────────────────────────────────────────────────────────


# Fields that flow from the DB into the runtime config. Everything else
# (client_id / client_secret / webhook_verifier_token / redirect_uri) is
# treated as env-only — those values must come from ``connector_configs``
# at request time so a stale or empty DB row can't disable signature
# verification or shadow rotated secrets.
_DB_OWNED_FIELDS: set[str] = {
    "access_token",
    "refresh_token",
    "access_token_expires_at",
    "realm_id",
    "environment",
}


async def _load_source_config(app: Any, source_id: str) -> dict[str, Any]:
    """Read ``connector_source.config`` JSON for *source_id*.

    Env config (``app.state.connector_configs['quickbooks']``) is the
    baseline; the DB row only contributes the per-realm dynamic fields
    (tokens, realm/environment). This way an empty or stale DB value can
    never override an env-provided secret.
    """
    from sqlalchemy import text

    factory = getattr(app.state, "session_factory", None)
    fallback: dict[str, Any] = getattr(app.state, "connector_configs", {}).get("quickbooks", {})
    merged: dict[str, Any] = dict(fallback)
    if factory is None:
        return merged
    async with factory() as session:
        result = await session.execute(
            text("SELECT config FROM connector_source WHERE id = :id"),
            {"id": source_id},
        )
        row = result.mappings().first()
    if row and row["config"]:
        try:
            parsed: dict[str, Any] = json.loads(row["config"])
        except json.JSONDecodeError:
            logger.warning("connector_source.config not JSON for %s", source_id)
        else:
            for key in _DB_OWNED_FIELDS:
                if key in parsed and parsed[key]:
                    merged[key] = parsed[key]
    return merged
