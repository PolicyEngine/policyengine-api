PYTHON_VERSION ?= 3.12
VENV_PYTHON := .venv/bin/python

.PHONY: bootstrap-dev install debug test-env-vars test debug-test lint format check-changelog pre-pr ci deploy changelog

bootstrap-dev:
	uv venv --seed --python $(PYTHON_VERSION)
	.venv/bin/python -m pip install -e ".[dev]"
	bash .github/setup_env.sh

install:
	python -m pip install -e ".[dev]"
	bash .github/setup_env.sh

debug:
	FLASK_APP=policyengine_api.api FLASK_DEBUG=1 $(VENV_PYTHON) -m flask run --without-threads

test-env-vars:
	$(VENV_PYTHON) -m pytest tests/env_variables

test:
	MAX_HOUSEHOLDS=1000 $(VENV_PYTHON) -m coverage run -a --branch -m pytest tests/to_refactor tests/unit --disable-pytest-warnings
	$(VENV_PYTHON) -m coverage xml -i

debug-test:
	MAX_HOUSEHOLDS=1000 FLASK_DEBUG=1 $(VENV_PYTHON) -m pytest -vv --durations=0 tests

lint:
	uvx --from 'ruff>=0.9.0' ruff format --check .

format:
	uvx --from 'ruff>=0.9.0' ruff format .

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
	$(VENV_PYTHON) .github/bump_version.py
	$(VENV_PYTHON) -m towncrier build --yes --version $$($(VENV_PYTHON) -c "import re; print(re.search(r'version = \"(.+?)\"', open('pyproject.toml').read()).group(1))")
