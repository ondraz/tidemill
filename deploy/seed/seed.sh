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
SEED_MONTHS="${SEED_MONTHS:-8}"

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
echo "=== Seeding Stripe test data ==="
uv run python "$ROOT/deploy/seed/stripe_seed.py" \
    --customers "$SEED_CUSTOMERS" --months "$SEED_MONTHS"

echo ""
echo "=== Waiting for webhook processing (30s) ==="
sleep 30

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

if [[ "$metrics" == '["churn","ltv","mrr","retention","trials"]' ]]; then
    echo "PASS: All metrics registered"
else
    echo "FAIL: Expected [churn, ltv, mrr, retention, trials], got: $metrics"
    errors=$((errors + 1))
fi

if [[ "$mrr" != "0" && "$mrr" != '"0"' && "$mrr" != "null" ]]; then
    echo "PASS: MRR is non-zero ($mrr cents)"
else
    echo "FAIL: MRR is zero or null"
    errors=$((errors + 1))
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
