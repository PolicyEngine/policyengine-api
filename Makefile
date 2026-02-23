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
	python .github/bump_version.py
	towncrier build --yes --version $$(python -c "import re; print(re.search(r'version = \"(.+?)\"', open('pyproject.toml').read()).group(1))")