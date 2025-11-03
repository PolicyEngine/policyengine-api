.PHONY: help
help:  ## Print this message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-24s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Install dependencies and setup env
	pip install -e ".[dev]" --config-settings editable_mode=compat
	bash .github/setup_env.sh

.PHONY: debug
debug: ## Run the Flask app in debug mode
	FLASK_APP=policyengine_api.api FLASK_DEBUG=1 flask run --without-threads --host=0.0.0.0

.PHONY: test-env-vars
test-env-vars: ## Test environment variables
	pytest tests/env_variables

test: ## Run tests
	MAX_HOUSEHOLDS=1000 coverage run -a --branch -m pytest tests/to_refactor tests/unit --disable-pytest-warnings
	coverage xml -i

debug-test: ## Run tests with debug verbosity
	MAX_HOUSEHOLDS=1000 FLASK_DEBUG=1 pytest -vv --durations=0 tests

format: ## Run the black formmater
	black . -l 79

deploy: ## Deploy to GCP
	python gcp/export.py
	gcloud config set app/cloud_build_timeout 2400
	cp gcp/policyengine_api/* .
	y | gcloud app deploy --service-account=github-deployment@policyengine-api.iam.gserviceaccount.com
	rm app.yaml
	rm Dockerfile
	rm .gac.json
	rm .dbpw

changelog: ## Build the changelog
	build-changelog changelog.yaml --output changelog.yaml --update-last-date --start-from 0.1.0 --append-file changelog_entry.yaml
	build-changelog changelog.yaml --org PolicyEngine --repo policyengine-api --output CHANGELOG.md --template .github/changelog_template.md
	bump-version changelog.yaml setup.py policyengine_api/constants.py
	rm changelog_entry.yaml || true
	touch changelog_entry.yaml 


COMPOSE_FILE := docker/docker-compose.yml
DOCKER_IMG=policyengine:policyengine-api
DOCKER_NAME=policyengine-api
ifeq (, $(shell which docker))
DOCKER_CONTAINER_ID := docker-is-not-installed
else
DOCKER_CONTAINER_ID := $(shell docker ps --filter ancestor=$(DOCKER_IMG) --format "{{.ID}}")
endif

.PHONY: docker-build
docker-build: ## Build the docker image
	docker compose --file $(COMPOSE_FILE) build --force-rm

.PHONY: docker-run
docker-run:  ## Run the app as docker container with supporing services
	docker compose --file $(COMPOSE_FILE) up

.PHONY: services-start
services-start:  ## Run the docker containers for supporting services (e.g. Redis)
	docker compose --file $(COMPOSE_FILE) up -d redis

.PHONY: docker-console
docker-console:  ## Open a one-off container bash session
	@docker run -p 8080:5000 -v $(PWD):/code \
   --network policyengine-api_default \
   --rm --name policyengine-api-console -it \
   $(DOCKER_IMG) bash
	@docker rm policyengine-api-console