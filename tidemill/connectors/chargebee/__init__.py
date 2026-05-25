"""Chargebee connector — revenue source.

Mirrors the Stripe reference implementation. Notable shape differences:

- Chargebee's product catalog is Item → Item Price (vs Stripe's Product →
  Price). We map both onto Tidemill's `product` / `plan` tables.
- Chargebee subscriptions expose ``mrr`` server-side, so this connector
  passes it through verbatim instead of re-computing — see the
  "MRR override" path documented in ``docs/architecture/connectors.md``.
- Chargebee's ``non_renewing`` flag maps to canonical
  ``pending_cancellation=true`` (the subscription is still active for the
  current period; cancellation takes effect at the end of it).
- Webhooks use HTTP Basic Auth, not HMAC signatures.
"""

from tidemill.connectors.chargebee.connector import ChargebeeConnector

__all__ = ["ChargebeeConnector"]
