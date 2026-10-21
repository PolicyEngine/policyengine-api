.PHONY: install setup-env debug debug-asgi test-env-vars test quality-guards typecheck-v2 debug-test format changelog

# Install and test in the environment uv.lock defines, on the Python version
# the Cloud Run image runs (gcp/cloud_run/Dockerfile). .python-version selects
# 3.14 for other uv commands; set UV_PYTHON to test another version.
export UV_PYTHON ?= 3.12

install:
	uv sync --frozen --extra dev

setup-env:
	bash .github/setup_env.sh

debug:
	FLASK_APP=policyengine_api.api FLASK_DEBUG=1 uv run --frozen --extra dev flask run --without-threads

debug-asgi:
	FLASK_DEBUG=1 uv run --frozen --extra dev uvicorn policyengine_api.asgi:app --reload --port 8000

test-env-vars:
	uv run --frozen --extra dev pytest tests/env_variables

test:
	MAX_HOUSEHOLDS=1000 uv run --frozen --extra dev coverage run -a --branch -m pytest tests/to_refactor tests/unit tests/contract tests/integration/test_budget_window_in_flight_dedupe.py --disable-pytest-warnings
	uv run --frozen --extra dev coverage xml -i

quality-guards:
	python scripts/run_quality_guards.py

typecheck-v2:
	uv run --frozen --extra dev mypy

debug-test:
	MAX_HOUSEHOLDS=1000 FLASK_DEBUG=1 uv run --frozen --extra dev pytest -vv --durations=0 tests

format:
	ruff format .

changelog:
	python .github/bump_version.py
	uv lock
	uv run --frozen --extra dev towncrier build --yes --version $$(python -c "import re; print(re.search(r'version = \"(.+?)\"', open('pyproject.toml').read()).group(1))")
