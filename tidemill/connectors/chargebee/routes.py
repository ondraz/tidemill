"""Chargebee webhook endpoint.

Chargebee posts JSON to a configured URL using HTTP Basic Auth — the
``Authorization: Basic ...`` header is the credential. The connector's
``verify_signature`` decodes that header and compares the username +
password against the configured CHARGEBEE_WEBHOOK_USERNAME /
CHARGEBEE_WEBHOOK_PASSWORD pair. Missing or wrong credentials → 401.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, Request, Response

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/chargebee")
async def receive_chargebee_webhook(
    request: Request,
    authorization: str | None = Header(None),
) -> Response:
    from tidemill.api.app import app
    from tidemill.connectors import get_connector

    body = await request.body()
    payload = await request.json()

    source_id = request.query_params.get("source_id", "chargebee")
    config = getattr(app.state, "connector_configs", {}).get("chargebee", {})

    connector = get_connector("chargebee", source_id=source_id, config=config)

    if not connector.verify_signature(body, authorization or ""):
        return Response(status_code=401, content="Invalid credentials")

    events = connector.translate(payload)
    if events:
        producer = app.state.producer
        await producer.publish_many(events)

    return Response(status_code=200, content="ok")
