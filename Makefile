.PHONY: help docs check check-integration seed dev dev-up dev-down dev-reset lint test typecheck install install-dev install-pre-commit frontend frontend-build dashboards-pull dashboards-diff

.DEFAULT_GOAL := help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies
	uv sync --frozen

install-pre-commit: ## Update and install pre-commit hooks
	uv run pre-commit autoupdate
	uv run pre-commit install

install-dev: ## Install dev dependencies + pre-commit hooks + post-checkout hook
	uv sync --frozen --extra dev
	cd frontend && npm install
	$(MAKE) install-pre-commit
	$(MAKE) install-post-hooks


check: lint test typecheck ## Run all checks (lint + test + typecheck)

lint: ## Run linter and format check
	uv run ruff check tidemill/ tests/
	uv run ruff format --check tidemill/ tests/

test: ## Run unit tests
	uv run pytest tests/ -v

typecheck: ## Run type checker
	uv run mypy


PG_CONTAINER := tidemill-test-pg
PG_PORT      := 5433
PG_USER      := tidemill
PG_PASSWORD  := password
PG_DB        := tidemill_test
TEST_DATABASE_URL := postgresql+asyncpg://$(PG_USER):$(PG_PASSWORD)@localhost:$(PG_PORT)/$(PG_DB)

check-integration: ## Run integration tests (starts PostgreSQL in Docker)
	@echo "Starting PostgreSQL container…"
	@docker rm -f $(PG_CONTAINER) 2>/dev/null || true
	@docker run -d --name $(PG_CONTAINER) \
		-e POSTGRES_USER=$(PG_USER) \
		-e POSTGRES_PASSWORD=$(PG_PASSWORD) \
		-e POSTGRES_DB=$(PG_DB) \
		-p $(PG_PORT):5432 \
		postgres:16-alpine >/dev/null
	@echo "Waiting for PostgreSQL to be ready…"
	@for i in 1 2 3 4 5 6 7 8 9 10; do \
		docker exec $(PG_CONTAINER) pg_isready -U $(PG_USER) -d $(PG_DB) >/dev/null 2>&1 && break; \
		sleep 1; \
	done
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) uv run pytest tests/ -m integration -v; \
		rc=$$?; \
		docker rm -f $(PG_CONTAINER) >/dev/null 2>&1; \
		exit $$rc


COMPOSE_LOCAL := docker compose -f deploy/compose/docker-compose.yml -f deploy/compose/docker-compose.observability.yml -f deploy/compose/docker-compose.local.yml

seed: ## Seed Stripe test data
	./deploy/seed/seed.sh --cleanup-only
	./deploy/seed/seed.sh
	@$(COMPOSE_LOCAL) stop


frontend: ## Start frontend dev server on :5173
	cd frontend && npm run dev

frontend-build: ## Build frontend for production
	cd frontend && npm ci && npm run build

COMPOSE_DEV := docker compose \
	-f deploy/compose/docker-compose.yml \
	-f deploy/compose/docker-compose.observability.yml \
	-f deploy/compose/docker-compose.dev.yml

dev-up: ## Start dev environment
	$(COMPOSE_DEV) up -d
	@echo ""
	@echo "Infrastructure running: PostgreSQL :5432, Redpanda :9092, OTEL :4317, Grafana :3000"
	@echo "Starting stripe listen (PID written to /tmp/stripe-listen-dev.pid)..."
	@stripe listen --forward-to http://localhost:8000/api/webhooks/stripe --latest > /tmp/stripe-listen-dev.log 2>&1 & echo $$! > /tmp/stripe-listen-dev.pid

dev-down: ## Stop dev environment
	@if [ -f /tmp/stripe-listen-dev.pid ]; then kill $$(cat /tmp/stripe-listen-dev.pid) 2>/dev/null || true; rm -f /tmp/stripe-listen-dev.pid; echo "Stopped stripe listen"; fi
	$(COMPOSE_DEV) down

dev-reset: ## Stop dev environment and delete volumes
	$(COMPOSE_DEV) down -v

dev: ## Start full dev environment + API + worker + frontend (stops services on exit)
	@$(MAKE) dev-up
	@echo "Starting API on :8000 (logs → Loki service=tidemill-api, file /tmp/tidemill-api-dev.log)..."
	@( uv run uvicorn tidemill.api.app:app --host 0.0.0.0 --port 8000 --reload 2>&1 | ./scripts/ship-to-loki.py --service tidemill-api ) > /tmp/tidemill-api-dev.log 2>&1 & echo $$! > /tmp/tidemill-api-dev.pid
	@echo "Starting worker (logs → Loki service=tidemill-worker, file /tmp/tidemill-worker-dev.log)..."
	@( uv run python -m tidemill.worker 2>&1 | ./scripts/ship-to-loki.py --service tidemill-worker ) > /tmp/tidemill-worker-dev.log 2>&1 & echo $$! > /tmp/tidemill-worker-dev.pid
	@trap 'pkill -f "uvicorn tidemill.api.app" 2>/dev/null; pkill -f "tidemill.worker" 2>/dev/null; pkill -f "ship-to-loki.py" 2>/dev/null; rm -f /tmp/tidemill-api-dev.pid /tmp/tidemill-worker-dev.pid; $(MAKE) -C "$(CURDIR)" dev-down' EXIT; cd frontend && npm run dev


docs: ## Start MkDocs dev server on :8001
	@echo "Starting MkDocs server..."
	uv run mkdocs serve -a 127.0.0.1:8001 -f docs/mkdocs.yml


dashboards-pull: ## Export Grafana dashboards to JSON files (then commit)
	@./scripts/grafana-dashboards.py pull

dashboards-diff: ## Show drift between Grafana's live dashboards and committed JSON
	@./scripts/grafana-dashboards.py diff


.PHONY: install-post-hooks
install-post-hooks: ## Install git post-checkout hook
	hooks_dir=$$(git rev-parse --git-path hooks) && \
	mkdir -p "$$hooks_dir" && \
	install -m 755 scripts/post-checkout-hook.sh "$$hooks_dir/post-checkout"

.PHONY: worktree-add
worktree-add: install-post-hooks ## Create a git worktree (requires BRANCH=name)
	@test -n "$(BRANCH)" || (echo "Error: BRANCH variable must be set" && exit 1)
	git worktree add "../tidemill-$(BRANCH)" -b "${BRANCH}" "origin/main"
