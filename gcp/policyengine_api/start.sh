# Start the API
gunicorn -b :$PORT policyengine_api.api --timeout 300 --workers 5 &
# Start the redis server
redis-server &
# Start the worker
ANTRHOPIC_API_TOKEN=$ANTHROPIC_API_TOKEN python3.9 policyengine_api/worker.py
