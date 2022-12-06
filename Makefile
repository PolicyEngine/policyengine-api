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
