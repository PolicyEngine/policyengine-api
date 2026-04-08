.PHONY: bootstrap-dev install debug test-env-vars test debug-test lint format check-changelog pre-pr ci deploy changelog

bootstrap-dev:
	uv venv
	uv pip install -e ".[dev]"
	bash .github/setup_env.sh

install:
	python -m pip install -e ".[dev]"
	bash .github/setup_env.sh

debug:
	FLASK_APP=policyengine_api.api FLASK_DEBUG=1 uv run flask run --without-threads

test-env-vars:
	uv run pytest tests/env_variables

test:
	MAX_HOUSEHOLDS=1000 uv run coverage run -a --branch -m pytest tests/to_refactor tests/unit --disable-pytest-warnings
	uv run coverage xml -i

debug-test:
	MAX_HOUSEHOLDS=1000 FLASK_DEBUG=1 uv run pytest -vv --durations=0 tests

lint:
	uv run ruff format --check .

format:
	uv run ruff format .

check-changelog:
	@FRAGMENTS=$$(find changelog.d -type f ! -name '.gitkeep' | wc -l); \
	if [ "$$FRAGMENTS" -eq 0 ]; then \
		echo "No changelog fragment found in changelog.d/"; \
		echo "Add one with: echo 'Description.' > changelog.d/$$(git branch --show-current).<type>.md"; \
		echo "Types: added, changed, fixed, removed, breaking"; \
		exit 1; \
	fi

pre-pr:
	$(MAKE) lint
	$(MAKE) check-changelog

ci:
	$(MAKE) pre-pr
	$(MAKE) test

deploy:
	python gcp/export.py
	gcloud config set app/cloud_build_timeout 2400
	cp gcp/policyengine_api/* .
	y | gcloud app deploy --service-account=github-deployment@policyengine-api.iam.gserviceaccount.com
	rm app.yaml
	rm Dockerfile
	rm .gac.json
	rm .dbpw

changelog:
	uv run python .github/bump_version.py
	uv run towncrier build --yes --version $$(uv run python -c "import re; print(re.search(r'version = \"(.+?)\"', open('pyproject.toml').read()).group(1))")
