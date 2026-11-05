# Proof fixture for api.quality.make-quality (accepted), read with
# accepted/pr.yml: make quality applies ruff's fixes, then make quality-check
# runs every check without changing files.

quality:
	uv run --frozen --extra dev ruff check --fix .
	uv run --frozen --extra dev ruff format .
	$(MAKE) quality-check

quality-check:
	uv lock --check
	uv run --frozen --extra dev ruff check .
	uv run --frozen --extra dev ruff format --check .
	uv run --frozen --extra dev lint-imports --config pyproject.toml
	uv run --frozen --extra dev mypy
	uv run --frozen --extra dev python scripts/run_quality_guards.py
