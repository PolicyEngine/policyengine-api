install:
	pip install -e .

debug:
	rm policyengine_api/data/policyengine.db || true
	FLASK_APP=policyengine_api.api FLASK_DEBUG=1 flask run

debug-compute:
	rm policyengine_api/data/policyengine.db || true
	FLASK_APP=policyengine_api.economy_api FLASK_DEBUG=1 flask run --port 5001

test:
	pytest tests

format:
	black . -l 79
