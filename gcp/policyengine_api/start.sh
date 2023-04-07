# Start the API
gunicorn -b :$PORT policyengine_api.api --timeout 300 --workers 1 &
# Start the redis server
redis-server &
# Start the worker
python3 policyengine_api/worker.py
