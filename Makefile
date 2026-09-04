install:
	pip install -e ".[dev]"

setup-env:
	bash .github/setup_env.sh

debug:
	FLASK_APP=policyengine_api.api FLASK_DEBUG=1 flask run --without-threads

debug-asgi:
	FLASK_DEBUG=1 uvicorn policyengine_api.asgi:app --reload --port 8000

test-env-vars:
	pytest tests/env_variables

test:
	MAX_HOUSEHOLDS=1000 python -m coverage run -a --branch -m pytest tests/to_refactor tests/unit tests/contract tests/integration/test_budget_window_in_flight_dedupe.py --disable-pytest-warnings
	python -m coverage xml -i

quality-guards:
	python scripts/run_quality_guards.py

typecheck-v2:
	uv run --frozen --extra dev mypy

debug-test:
	MAX_HOUSEHOLDS=1000 FLASK_DEBUG=1 pytest -vv --durations=0 tests

format:
	ruff format .

changelog:
	python .github/bump_version.py
	towncrier build --yes --version $$(python -c "import re; print(re.search(r'version = \"(.+?)\"', open('pyproject.toml').read()).group(1))")
