.PHONY: docs docs-build

docs:
	@echo "Starting MkDocs server..."
	uv tool run --from mkdocs-material mkdocs serve -f docs/mkdocs.yml
