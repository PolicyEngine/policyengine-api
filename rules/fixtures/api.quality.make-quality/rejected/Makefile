# Proof fixture for api.quality.make-quality (rejected), read with
# rejected/pr.yml: make quality-check leaves out mypy, and pr.yml
# type-checks in a job of its own, so a local run and CI can differ.

quality:
	uv run --frozen --extra dev ruff check --fix .
	uv run --frozen --extra dev ruff format .
	$(MAKE) quality-check

quality-check:
	uv lock --check
	uv run --frozen --extra dev ruff check .
	uv run --frozen --extra dev ruff format --check .
	uv run --frozen --extra dev lint-imports --config pyproject.toml
	RULES_BASE_REF=$$(git merge-base HEAD origin/$${GITHUB_BASE_REF:-master}) uv run --frozen --extra dev python -S scripts/run_quality_guards.py
