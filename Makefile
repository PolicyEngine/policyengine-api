.PHONY: install setup-env debug debug-asgi test-env-vars test quality quality-check quality-guards typecheck-v2 debug-test format changelog

# Install and test in the environment uv.lock defines, on the Python version
# the Cloud Run image runs (gcp/cloud_run/Dockerfile). .python-version selects
# 3.14 for other uv commands; set UV_PYTHON to test another version.
export UV_PYTHON ?= 3.12

# Turns on the pre-commit hook that runs make quality before each commit
# (.githooks/pre-commit, api.quality.pre-commit-hook), then installs the locked
# dev environment. core.hooksPath is shared by every worktree of the clone;
# outside a git repository there is nothing to turn on.
install:
	if git rev-parse --git-dir >/dev/null 2>&1; then git config core.hooksPath .githooks; fi
	uv sync --frozen --extra dev

setup-env:
	bash .github/setup_env.sh

debug:
	FLASK_APP=policyengine_api.api FLASK_DEBUG=1 uv run --frozen --extra dev flask run --without-threads

debug-asgi:
	FLASK_DEBUG=1 uv run --frozen --extra dev uvicorn policyengine_api.asgi:app --reload --port 8000

test-env-vars:
	uv run --frozen --extra dev pytest tests/env_variables

# The two integration files need no database, network or credentials. The
# second runs the installed US model, in both the pull request and release runs.
test:
	MAX_HOUSEHOLDS=1000 uv run --frozen --extra dev --group telemetry-error-issues coverage run -a --branch -m pytest tests/to_refactor tests/unit tests/contract tests/integration/test_budget_window_in_flight_dedupe.py tests/integration/test_installed_us_model_spm.py --disable-pytest-warnings
	uv run --frozen --extra dev coverage xml -i

# The quality checks, the same locally and in pr.yml's quality-guards job
# (api.quality.make-quality): ruff's fixes first, then every check.
quality:
	uv run --frozen --extra dev ruff check --fix .
	uv run --frozen --extra dev ruff format .
	$(MAKE) quality-check

# Every check, changing no file. diff-cover isn't here: it needs every test
# shard's coverage report, so pr.yml runs it in a job of its own. The quality
# guards run without site-packages (python -S), so they keep to the standard
# library as push.yml runs them. The rules guard compares baselines and rule
# statuses with RULES_BASE_REF: the commit HEAD shares with the base branch,
# which CI names in GITHUB_BASE_REF, or master. So a branch is compared with
# where it left master, as CI compares its merge with master.
quality-check:
	uv lock --check
	uv run --frozen --extra dev ruff check .
	uv run --frozen --extra dev ruff format --check .
	uv run --frozen --extra dev lint-imports --config pyproject.toml
	uv run --frozen --extra dev mypy
	RULES_BASE_REF=$$(git merge-base HEAD origin/$${GITHUB_BASE_REF:-master}) uv run --frozen --extra dev python -S scripts/run_quality_guards.py

quality-guards:
	python scripts/run_quality_guards.py

typecheck-v2:
	uv run --frozen --extra dev mypy

debug-test:
	MAX_HOUSEHOLDS=1000 FLASK_DEBUG=1 uv run --frozen --extra dev --group telemetry-error-issues pytest -vv --durations=0 tests

format:
	ruff format .

changelog:
	python .github/bump_version.py
	uv lock
	uv run --frozen --extra dev towncrier build --yes --version $$(python -c "import re; print(re.search(r'version = \"(.+?)\"', open('pyproject.toml').read()).group(1))")
