#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# End-to-end Stripe integration test using local Docker Compose stack.
#
# Prerequisites:
#   - Docker running
#   - Stripe CLI logged in (stripe login)
#   - STRIPE_API_KEY env var set (sk_test_...)
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

# Wait for stripe listen to output the webhook signing secret
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

echo ""
echo "=== Pre-seeding fx_rate (Frankfurter / ECB) ==="
# Populate fx_rate before generating subscriptions so historical billing
# dates can resolve EUR/GBP → USD without dead-lettering metric events.
$COMPOSE exec -T api tidemill fx-sync \
    || echo "WARN: fx-sync failed (continuing — events may dead-letter on FxRateMissingError)"

echo ""
echo "=== Seeding Stripe test data ==="
uv run python "$ROOT/deploy/seed/stripe_seed.py" \
    --customers "$SEED_CUSTOMERS" --months "$SEED_MONTHS"

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

if [[ "$metrics" == '["churn","expenses","ltv","mrr","retention","trials"]' ]]; then
    echo "PASS: All metrics registered"
else
    echo "FAIL: Expected [churn, expenses, ltv, mrr, retention, trials], got: $metrics"
    errors=$((errors + 1))
fi

if [[ "$mrr" != "0" && "$mrr" != '"0"' && "$mrr" != "null" ]]; then
    echo "PASS: MRR is non-zero ($mrr cents)"
else
    echo "FAIL: MRR is zero or null"
    errors=$((errors + 1))
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
