install:
	pip install -e .

debug:
	FLASK_APP=policyengine_api.api FLASK_DEBUG=1 flask run

debug-compute:
	FLASK_APP=policyengine_api.compute FLASK_DEBUG=1 flask run --port 5001

test:
	pytest tests

format:
	black . -l 79
