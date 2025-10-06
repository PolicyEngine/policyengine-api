install:
	pip install -e ".[dev]" --config-settings editable_mode=compat
	bash .github/setup_env.sh

debug:
	FLASK_APP=policyengine_api.api FLASK_DEBUG=1 flask run --without-threads

test-env-vars:
	pytest tests/env_variables

test:
	MAX_HOUSEHOLDS=1000 coverage run -a --branch -m pytest tests/to_refactor tests/unit --disable-pytest-warnings
	coverage xml -i

debug-test:
	MAX_HOUSEHOLDS=1000 FLASK_DEBUG=1 pytest -vv --durations=0 tests

format:
	black . -l 79

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
docker-build:
	docker compose --file $(COMPOSE_FILE) build --force-rm

.PHONY: docker-run
docker-run:  ## Run the app as docker container
	docker compose --file $(COMPOSE_FILE) up

.PHONY: docker-console
docker-console:  ## opens a one-off console container
	@docker run -p 8080:5000 -v $(PWD):/code \
   --network policyengine-api_default \
   --rm --name policyengine-api-console -it \
   $(DOCKER_IMG) bash
	@docker rm policyengine-api-console