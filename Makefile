.PHONY: docs check check-integration check-e2e dev dev-down dev-reset lint test typecheck install install-dev install-pre-commit

install:
	uv sync --frozen

install-pre-commit:
	uv run pre-commit autoupdate
	uv run pre-commit install

install-dev:
	uv sync --frozen --extra dev
	$(MAKE) install-pre-commit


check: lint test typecheck

lint:
	uv run ruff check subscriptions/ tests/
	uv run ruff format --check subscriptions/ tests/

test:
	uv run pytest tests/ -v

typecheck:
	uv run mypy


PG_CONTAINER := subscriptions-test-pg
PG_PORT      := 5433
PG_USER      := subscriptions
PG_PASSWORD  := password
PG_DB        := subscriptions_test
TEST_DATABASE_URL := postgresql+asyncpg://$(PG_USER):$(PG_PASSWORD)@localhost:$(PG_PORT)/$(PG_DB)

check-integration:
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


COMPOSE_LOCAL := docker compose -f deploy/compose/docker-compose.yml -f deploy/compose/docker-compose.local.yml

check-e2e:
	@test -n "$(STRIPE_API_KEY)" || (echo "Error: STRIPE_API_KEY must be set" && exit 1)
	STRIPE_API_KEY=$(STRIPE_API_KEY) ./scripts/test-e2e.sh --cleanup-only
	STRIPE_API_KEY=$(STRIPE_API_KEY) ./scripts/test-e2e.sh
	@POSTGRES_PASSWORD=test $(COMPOSE_LOCAL) stop


COMPOSE_DEV := docker compose -f deploy/compose/docker-compose.yml -f deploy/compose/docker-compose.dev.yml

dev:
	POSTGRES_PASSWORD=test $(COMPOSE_DEV) up -d
	@echo ""
	@echo "Infrastructure running: PostgreSQL :5432, Redpanda :9092"
	@echo "Start API and Worker from VS Code (F5) or:"
	@echo "  SUBSCRIPTIONS_DATABASE_URL=postgresql+asyncpg://subscriptions:test@localhost:5432/subscriptions \\"
	@echo "  KAFKA_BOOTSTRAP_SERVERS=localhost:9092 \\"
	@echo "  uv run uvicorn subscriptions.api.app:app --port 8000 --reload"

dev-down:
	POSTGRES_PASSWORD=test $(COMPOSE_DEV) down

dev-reset:
	POSTGRES_PASSWORD=test $(COMPOSE_DEV) down -v


docs:
	@echo "Starting MkDocs server..."
	uv tool run --from mkdocs-material mkdocs serve -f docs/mkdocs.yml


.PHONY: install-post-hooks
install-post-hooks:
	hooks_dir=$$(git rev-parse --git-path hooks) && \
	mkdir -p "$$hooks_dir" && \
	install -m 755 scripts/post-checkout-hook.sh "$$hooks_dir/post-checkout"

.PHONY: worktree-add
worktree-add: install-post-hooks
	@test -n "$(BRANCH)" || (echo "Error: BRANCH variable must be set" && exit 1)
	git worktree add "../subscriptions-$(BRANCH)" -b "${BRANCH}" "origin/main"
