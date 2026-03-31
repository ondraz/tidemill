.PHONY: docs check lint test typecheck install install-dev install-pre-commit

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
