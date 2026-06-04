#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# End-to-end seed using the local Docker Compose stack.
#
# Stripe is always seeded; QuickBooks (expenses) and Chargebee (alternate
# revenue source) are opt-in via their env vars and skipped silently when
# unset, so a Stripe-only contributor isn't forced through their setup.
#
# Prerequisites:
#   - Docker running
#   - Stripe CLI logged in (stripe login)
#   - STRIPE_API_KEY env var set (sk_test_...)
#   - STRIPE_CLI_WEBHOOK_SECRET in deploy/compose/.env matches the whsec
#     printed by `stripe listen` (the CLI device secret). Production's
#     STRIPE_WEBHOOK_SECRET is intentionally NOT used here.
#
# Optional — Chargebee fan-out (triggers when both env vars are set):
#   - CHARGEBEE_SITE / CHARGEBEE_API_KEY for a Chargebee Test Site
#   - `tailscale` CLI on PATH with Funnel enabled for this device (see
#     docs/development/testing.md — one-time admin-console step)
#   - Webhook already configured in Chargebee → Settings → Webhooks
#     against https://<host>.<tailnet>.ts.net/api/webhooks/chargebee
#     with Basic Auth = CHARGEBEE_WEBHOOK_USERNAME/_PASSWORD
#
# Usage:
#   ./deploy/seed/seed.sh
#   ./deploy/seed/seed.sh --cleanup-only
# ---------------------------------------------------------------------------
set -euo pipefail

: "${STRIPE_API_KEY:?Set STRIPE_API_KEY (sk_test_...)}"

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_DIR="$ROOT/deploy/compose"
COMPOSE="docker compose -f $COMPOSE_DIR/docker-compose.yml -f $COMPOSE_DIR/docker-compose.observability.yml -f $COMPOSE_DIR/docker-compose.local.yml"
API="http://localhost:8000"
SEED_CUSTOMERS="${SEED_CUSTOMERS:-19}"
SEED_MONTHS="${SEED_MONTHS:-18}"

full_cleanup() {
    echo ""
    echo "=== Full cleanup ==="
    # Stop stripe listen
    if [[ -n "${STRIPE_PID:-}" ]]; then
        kill "$STRIPE_PID" 2>/dev/null || true
        wait "$STRIPE_PID" 2>/dev/null || true
    fi
    # Stop compose and delete volumes
    $COMPOSE down -v --remove-orphans 2>/dev/null || true
    echo "Stopped Docker Compose (volumes removed)"
    # Cleanup Stripe test clocks
    echo "Cleaning up Stripe test clocks..."
    uv run python "$ROOT/deploy/seed/stripe_seed.py" --cleanup 2>/dev/null || true
    echo "Done."
}

stop_stripe_listen() {
    if [[ -n "${STRIPE_PID:-}" ]]; then
        kill "$STRIPE_PID" 2>/dev/null || true
        wait "$STRIPE_PID" 2>/dev/null || true
        echo "Stopped stripe listen"
    fi
}

if [[ "${1:-}" == "--cleanup-only" ]]; then
    full_cleanup
    exit 0
fi

trap stop_stripe_listen EXIT

echo "=== Starting local stack ==="
export AUTH_ENABLED=false
# Clear any host-shell STRIPE_WEBHOOK_SECRET / STRIPE_CLI_WEBHOOK_SECRET so
# compose's ${VAR:-} interpolation falls through to deploy/compose/.env.
# direnv-loaded shells carry the .env value as a real export, so a stale
# shell value would otherwise mask a freshly-updated .env and the API
# would boot with the wrong whsec — every webhook then fails signature
# verification with 400.
unset STRIPE_WEBHOOK_SECRET
unset STRIPE_CLI_WEBHOOK_SECRET
$COMPOSE up -d --build --wait 2>&1 | tail -5

echo ""
echo "=== Waiting for API ==="
for i in $(seq 1 90); do
    if curl -sf "$API/healthz" >/dev/null 2>&1; then
        echo "API ready (${i}s)"
        break
    fi
    if [[ $i -eq 90 ]]; then
        echo "ERROR: API not ready after 90s"
        docker logs compose-api-1 2>&1 | tail -20
        exit 1
    fi
    sleep 1
done

echo ""
echo "=== Starting stripe listen ==="
stripe listen --forward-to "$API/api/webhooks/stripe" --latest > /tmp/stripe-listen.log 2>&1 &
STRIPE_PID=$!

# Wait for stripe listen to output the webhook signing secret, then check
# it matches what the API container booted with — they must agree or every
# forwarded webhook fails signature verification with 400 and the seed
# silently produces no data.
for i in $(seq 1 30); do
    WHSEC=$(grep -o 'whsec_[a-zA-Z0-9_]*' /tmp/stripe-listen.log 2>/dev/null | head -1) || true
    if [[ -n "${WHSEC:-}" ]]; then break; fi
    sleep 1
done
if [[ -z "${WHSEC:-}" ]]; then
    echo "ERROR: stripe listen didn't produce a webhook secret"
    cat /tmp/stripe-listen.log
    exit 1
fi
echo "Webhook secret: ${WHSEC:0:12}..."

API_WHSEC=$($COMPOSE exec -T api printenv STRIPE_WEBHOOK_SECRET 2>/dev/null | tr -d '\r' || echo "")
if [[ "$API_WHSEC" != "$WHSEC" ]]; then
    echo "ERROR: webhook secret mismatch — API has '${API_WHSEC:0:12}...', stripe listen signs with '${WHSEC:0:12}...'"
    echo "       Set STRIPE_CLI_WEBHOOK_SECRET in deploy/compose/.env to the CLI's whsec, then re-run."
    echo "       (STRIPE_WEBHOOK_SECRET stays reserved for the deployed production endpoint.)"
    exit 1
fi

echo ""
echo "=== Pre-seeding fx_rate (Frankfurter / ECB) ==="
# Populate fx_rate before generating subscriptions so historical billing
# dates can resolve EUR/GBP → USD without dead-lettering metric events.
# Force a 2-year backfill: the API's periodic sync may have already pulled
# the last few days, in which case an unqualified fx-sync would skip older
# gaps and the seed's 18-month history would dead-letter.
# `tidemill` lives in the container's uv-managed venv (not on PATH), so
# go through `uv run`.
FX_SINCE=$(python3 -c 'from datetime import date,timedelta; print((date.today()-timedelta(days=730)).isoformat())')
$COMPOSE exec -T api uv run tidemill fx-sync --since "$FX_SINCE" \
    || echo "WARN: fx-sync failed (continuing — events may dead-letter on FxRateMissingError)"

echo ""
echo "=== Seeding Stripe test data ==="
uv run python "$ROOT/deploy/seed/stripe_seed.py" \
    --customers "$SEED_CUSTOMERS" --months "$SEED_MONTHS"

echo ""
echo "=== Seeding Chargebee test data (Test Site) ==="
# Optional: requires a Chargebee Test Site (one-time setup — see
# docs/development/testing.md). When CHARGEBEE_SITE / CHARGEBEE_API_KEY
# are unset, skip silently so contributors with only Stripe configured
# aren't blocked.
if [[ -n "${CHARGEBEE_SITE:-}" && -n "${CHARGEBEE_API_KEY:-}" ]]; then
    # Ensure the chargebee connector_source row exists. The default
    # bootstrap in api/app.py only inserts the row matching the active
    # TIDEMILL_CONNECTOR; multi-source seeds need each row added explicitly
    # before webhooks can attach events to a source_id.
    $COMPOSE exec -T postgres psql -U tidemill -d tidemill -v ON_ERROR_STOP=1 -c \
        "INSERT INTO connector_source (id, type, name, created_at)
         VALUES ('chargebee', 'chargebee', 'Chargebee', NOW())
         ON CONFLICT (id) DO NOTHING;" >/dev/null \
        || echo "WARN: couldn't ensure chargebee connector_source row"

    # Start Tailscale Funnel so Chargebee's webhook deliveries can reach
    # this machine. Funnel preserves the URL across runs, so the
    # one-time webhook URL configured in Chargebee → Settings → Webhooks
    # keeps working without re-registration. We don't tear it down at
    # script exit — `make chargebee-funnel-down` when you're done.
    if command -v tailscale >/dev/null 2>&1; then
        tailscale funnel --bg 8000 \
            || echo "WARN: tailscale funnel failed (Funnel not enabled on this device? see docs/development/testing.md)"
        echo "Tailscale Funnel mappings:"
        tailscale funnel status || true
    else
        echo "WARN: tailscale CLI not on PATH — webhook delivery will not work locally"
    fi

    uv run python "$ROOT/deploy/seed/chargebee_seed.py" \
        --customers "$SEED_CUSTOMERS" --months "$SEED_MONTHS" \
        || echo "WARN: chargebee_seed.py failed (continuing — Stripe data still present)"
else
    echo "(skipped — set CHARGEBEE_SITE and CHARGEBEE_API_KEY to enable)"
fi

echo ""
echo "=== Seeding QuickBooks expense data (sandbox) ==="
# Optional: requires sandbox OAuth credentials (one-time setup — see
# docs/development/testing.md). When unset, skip the QBO seed so
# contributors with only Stripe configured aren't blocked.
if [[ -n "${QUICKBOOKS_SANDBOX_REFRESH_TOKEN:-}" && -n "${QUICKBOOKS_SANDBOX_REALM_ID:-}" ]]; then
    uv run python "$ROOT/deploy/seed/quickbooks_seed.py" --months "$SEED_MONTHS" \
        || echo "WARN: quickbooks_seed.py failed (continuing — Stripe data still present)"

    # QBO seed inserts entities directly via API — they must be backfilled
    # into Tidemill's Kafka pipeline so state consumers populate the base
    # tables and the expenses metric returns non-zero results.
    echo ""
    echo "=== Triggering QuickBooks backfill ==="
    QBO_SOURCE_ID="quickbooks-${QUICKBOOKS_SANDBOX_REALM_ID}"
    curl -sf -X POST "$API/api/sources/$QBO_SOURCE_ID/backfill" \
        || echo "WARN: backfill trigger failed (source row may not exist yet — complete the OAuth flow first)"
else
    echo "(skipped — set QUICKBOOKS_SANDBOX_REFRESH_TOKEN and QUICKBOOKS_SANDBOX_REALM_ID to enable)"
fi

echo ""
echo "=== Waiting for webhook + backfill processing (30s) ==="
sleep 30

echo ""
echo "=== Importing external customer attributes (CSV) ==="
# Adds account_manager / region / industry / is_strategic to the 19
# archetype customers via POST /api/attributes/import.  Matched by email
# since seed customer emails are deterministic (seed-N@test.example.com).
# These attributes power the example segments created below — anything
# that's not in Stripe metadata still lands in the segment builder.
ATTRS_CSV="$ROOT/deploy/seed/customer_attributes.csv"
if [[ -f "$ATTRS_CSV" ]]; then
    import_result=$(curl -sf -X POST "$API/api/attributes/import" \
        -F "file=@$ATTRS_CSV" \
        -F "id_column=email" \
        -F "id_kind=email" || echo "CURL_FAILED")
    echo "Import: $import_result"
else
    echo "WARN: $ATTRS_CSV missing — skipping attribute import"
fi

echo ""
echo "=== Creating example segments ==="
# Two starter segments so a fresh stack has something for the SegmentPicker
# to bind to.  Use the /api/segments endpoint directly — these are
# workspace-shared so no auth scoping is needed when AUTH_ENABLED=false.
strategic_def='{"version":1,"root":{"op":"and","conditions":[{"field":"attr.is_strategic","op":"=","value":true}]}}'
emea_def='{"version":1,"root":{"op":"and","conditions":[{"field":"attr.region","op":"=","value":"EMEA"}]}}'
curl -sf -X POST "$API/api/segments" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"Strategic accounts\",\"description\":\"is_strategic = true\",\"definition\":$strategic_def}" \
    >/dev/null && echo "  Created segment: Strategic accounts"
curl -sf -X POST "$API/api/segments" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"EMEA region\",\"description\":\"region = EMEA\",\"definition\":$emea_def}" \
    >/dev/null && echo "  Created segment: EMEA region"

echo ""
echo "=== Checking results ==="
echo ""

# Sources
sources=$(curl -sf "$API/api/sources" || echo "CURL_FAILED")
echo "Sources: $sources"

# Metrics
metrics=$(curl -sf "$API/api/metrics" || echo "CURL_FAILED")
echo "Metrics: $metrics"

# MRR
mrr=$(curl -sf "$API/api/metrics/mrr?at=2026-03-01" || echo "CURL_FAILED")
echo "MRR at 2026-03-01: $mrr cents"

# ARR
arr=$(curl -sf "$API/api/metrics/arr?at=2026-03-01" || echo "CURL_FAILED")
echo "ARR at 2026-03-01: $arr cents"

# MRR breakdown
echo ""
echo "MRR breakdown (full period):"
curl -sf "$API/api/metrics/mrr/breakdown?start=2025-09-01&end=2026-03-31" | python3 -m json.tool || echo "(failed)"

# Retention
echo ""
echo "Retention:"
curl -sf "$API/api/metrics/retention?start=2025-09-01&end=2026-03-31" | python3 -m json.tool || echo "(failed)"

echo ""
echo "=== Validating ==="
errors=0

if [[ "$sources" == "[]" ]]; then
    echo "FAIL: No sources registered"
    errors=$((errors + 1))
else
    echo "PASS: Sources present"
fi

if [[ "$metrics" == '["churn","expenses","ltv","mrr","retention","trials","usage_revenue"]' ]]; then
    echo "PASS: All metrics registered"
else
    echo "FAIL: Expected [churn, expenses, ltv, mrr, retention, trials, usage_revenue], got: $metrics"
    errors=$((errors + 1))
fi

# API returns the snapshot as a JSON number (e.g. 0, 0.0, 1234567.0) — treat
# any value that parses to a positive float as a pass.
mrr_positive=$(python3 -c "import sys; v=sys.argv[1]; print('1' if v not in ('','null','CURL_FAILED') and float(v) > 0 else '0')" "$mrr" 2>/dev/null || echo "0")
if [[ "$mrr_positive" == "1" ]]; then
    echo "PASS: MRR is non-zero ($mrr cents)"
else
    echo "FAIL: MRR is zero or null ($mrr)"
    errors=$((errors + 1))
fi

# Chargebee data only checked when the Chargebee seed actually ran
# (matches the gating condition in the seed step above — both env vars
# required). We check customer rows tagged with the chargebee source_id
# rather than MRR since the Stripe seed already covered MRR globally.
if [[ -n "${CHARGEBEE_SITE:-}" && -n "${CHARGEBEE_API_KEY:-}" ]]; then
    cb_customers=$($COMPOSE exec -T postgres psql -U tidemill -d tidemill -tA -c \
        "SELECT COUNT(*) FROM customer WHERE source_id = 'chargebee';" 2>/dev/null | tr -d '[:space:]' || echo "0")
    if [[ "$cb_customers" != "0" ]]; then
        echo "PASS: Chargebee customers ingested ($cb_customers rows)"
    else
        echo "FAIL: No Chargebee customers — check Funnel + webhook config (Settings → Webhooks)"
        errors=$((errors + 1))
    fi
fi

# Expense data only checked when the QBO seed actually ran (matches the
# gating condition in the seed step above — both env vars are required).
if [[ -n "${QUICKBOOKS_SANDBOX_REFRESH_TOKEN:-}" && -n "${QUICKBOOKS_SANDBOX_REALM_ID:-}" ]]; then
    expenses=$(curl -sf "$API/api/metrics/expenses?start=2025-09-01&end=2026-03-31" || echo "CURL_FAILED")
    expenses_total=$(echo "$expenses" | python3 -c "import json,sys; print(json.load(sys.stdin).get('total_base_cents', 0))" 2>/dev/null || echo "0")
    if [[ "$expenses_total" != "0" && "$expenses_total" != "null" ]]; then
        echo "PASS: Expense data present ($expenses_total cents)"
    else
        echo "FAIL: No expense data — QBO seed may have failed or backfill is still running"
        errors=$((errors + 1))
    fi
fi

echo ""
if [[ $errors -eq 0 ]]; then
    echo "All checks passed!"
    echo ""
    echo "Data is preserved. To continue developing:"
    echo "  make dev          # restart infra (postgres + redpanda)"
    echo "  # then run API from VS Code (F5) or terminal"
else
    echo "$errors check(s) failed."
    exit 1
fi
