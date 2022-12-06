install:
	pip install -e .

debug:
	FLASK_APP=policyengine_api.api FLASK_DEBUG=1 flask run --without-threads

debug-compute:
	FLASK_APP=policyengine_api.economy_api FLASK_DEBUG=1 flask run --port 5001 --without-threads
test:
	pytest tests

format:
	black . -l 79

deploy:
	cat ${GOOGLE_APPLICATION_CREDENTIALS} > .gac.json
	echo ${POLICYENGINE_DB_PASSWORD} > .dbpw.json
	gcloud config set app/cloud_build_timeout 6000
	y | gcloud app deploy --service-account=github-deployment@policyengine-api.iam.gserviceaccount.com
	rm .gac.json