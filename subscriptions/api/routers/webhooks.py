"""Webhook ingestion endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Header, Request, Response

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/{source_type}")
async def receive_webhook(
    source_type: str,
    request: Request,
    stripe_signature: str | None = Header(None),
) -> Response:
    from subscriptions.api.app import app
    from subscriptions.connectors import get_connector

    body = await request.body()
    payload = await request.json()

    # Source ID comes from config or defaults to source_type.
    source_id = request.query_params.get("source_id", source_type)
    config = getattr(app.state, "connector_configs", {}).get(source_type, {})

    connector = get_connector(source_type, source_id=source_id, config=config)

    if stripe_signature and not connector.verify_signature(body, stripe_signature):
        return Response(status_code=400, content="Invalid signature")

    events = connector.translate(payload)
    if events:
        producer = app.state.producer
        await producer.publish_many(events)

    return Response(status_code=200, content="ok")
