install:
	pip install -e .

debug:
	FLASK_APP=policyengine_api.api FLASK_DEBUG=1 flask run --without-threads

debug-compute:
	FLASK_APP=policyengine_api.compute_api FLASK_DEBUG=1 flask run --port 5001 --without-threads
test:
	pytest tests

format:
	black . -l 79

deploy-api:
	cat ${GOOGLE_APPLICATION_CREDENTIALS} > .gac.json
	echo ${POLICYENGINE_DB_PASSWORD} > .dbpw
	gcloud config set app/cloud_build_timeout 6000
	cp gcp/policyengine_api/* .
	y | gcloud app deploy --service-account=github-deployment@policyengine-api.iam.gserviceaccount.com
	rm app.yaml
	rm Dockerfile
	rm .gac.json
	rm .dbpw
deploy-compute-api:
	cat ${GOOGLE_APPLICATION_CREDENTIALS} > .gac.json
	echo ${POLICYENGINE_DB_PASSWORD} > .dbpw
	gcloud config set app/cloud_build_timeout 6000
	cp gcp/compute_api/* .
	y | gcloud app deploy --service-account=github-deployment@policyengine-api.iam.gserviceaccount.com
	rm app.yaml
	rm Dockerfile
	rm .gac.json
	rm .dbpw

deploy: deploy-api deploy-compute-api
