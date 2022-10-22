install:
	pip install -e .

debug:
	FLASK_APP=policyengine_api/api.py FLASK_DEBUG=1 flask run

test:
	pytest tests

format:
	black . -l 79
