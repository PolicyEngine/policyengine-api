install:
	pip install -e .

debug:
	FLASK_APP=policyengine_api.api FLASK_DEBUG=1 flask run --without-threads

debug-compute:
	FLASK_APP=policyengine_api.compute_api FLASK_DEBUG=1 flask run --port 5001 --without-threads
test:
	pytest tests/api

test-compute:
	pytest tests/compute_api

format:
	black . -l 79

deploy-api:
	python gcp/export.py
	gcloud config set app/cloud_build_timeout 1200
	cp gcp/policyengine_api/* .
	y | gcloud app deploy --service-account=github-deployment@policyengine-api.iam.gserviceaccount.com
	rm app.yaml
	rm Dockerfile
	rm .gac.json
	rm .dbpw
deploy-compute-api:
	python gcp/export.py
	gcloud config set app/cloud_build_timeout 1200
	cp gcp/compute_api/* .
	y | gcloud app deploy --service-account=github-deployment@policyengine-api.iam.gserviceaccount.com
	rm app.yaml
	rm Dockerfile
	rm .gac.json
	rm .dbpw

deploy: deploy-api deploy-compute-api

changelog:
	build-changelog changelog.yaml --output changelog.yaml --update-last-date --start-from 0.1.0 --append-file changelog_entry.yaml
	build-changelog changelog.yaml --org PolicyEngine --repo policyengine-api --output CHANGELOG.md --template .github/changelog_template.md
	bump-version changelog.yaml setup.py policyengine_api/constants.py
	rm changelog_entry.yaml || true
	touch changelog_entry.yaml 