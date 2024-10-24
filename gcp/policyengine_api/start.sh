# Start the API
gunicorn -b :$PORT policyengine_api.api --timeout 300 --workers 5 &
# Start the redis server
redis-server &
# Start the worker
ANTHROPIC_API_TOKEN=$ANTHROPIC_API_TOKEN python3.11 policyengine_api/worker.py
