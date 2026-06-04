#!/usr/bin/env bash
# Runs on the production server. Invoked via `make deploy` (locally or from CI).
# Expects REF env var (git tag, branch, or commit sha) to check out before
# rebuilding the Compose stack.
set -euxo pipefail

: "${REF:?REF is required}"

cd /opt/tidemill

# Make sure /opt/tidemill is a clean mirror of $REF for the tracked files.
# - fetch all branches/tags and prune deleted ones
# - reset --hard to overwrite any drift in tracked files (missing files,
#   stale routes.tsx vs. missing pages/*, half-applied prior deploys)
# - clean -fd removes untracked files only; gitignored files (notably
#   deploy/compose/.env which holds production secrets) are preserved.
git fetch --prune --tags --force origin '+refs/heads/*:refs/remotes/origin/*'
git reset --hard "$REF"
git clean -fd
git rev-parse HEAD

docker compose -f deploy/compose/docker-compose.yml build

# The built SPA bundle ships inside the api image at /srv/frontend, but Caddy
# serves it from the `frontend_assets` named volume. Docker only copies image
# contents into a named volume when that volume is *first created* — on a
# redeploy the existing volume shadows the freshly built bundle, so the
# dashboard would keep serving stale assets (e.g. a new "Group by" dimension
# never appears). Tear the stack down and drop only the frontend volume so the
# next `up` repopulates it from the new image. `down` preserves named data
# volumes (postgres_data, redpanda_data, caddy_data) — only `-v` removes those.
docker compose -f deploy/compose/docker-compose.yml down
docker volume ls -q --filter name=frontend_assets | xargs -r docker volume rm

docker compose -f deploy/compose/docker-compose.yml up -d --force-recreate
