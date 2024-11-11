#!/bin/bash

# Environment variables
export PORT=${PORT:-8080}
export WORKER_COUNT=${WORKER_COUNT:-3}
export REDIS_PORT=${REDIS_PORT:-6379}

# Start the API
gunicorn -b :$PORT policyengine_api.api --timeout 300 --workers 5 &

# Start Redis with configuration for multiple clients
redis-server --protected-mode no \
             --maxclients 10000 \
             --timeout 0 &

# Wait for Redis to be ready
sleep 2

# Start multiple workers
for (( i=1; i<=$WORKER_COUNT; i++ ))
do
    echo "Starting worker $i..."
    python3 policyengine_api/worker.py &
done

# Keep the script running and handle shutdown gracefully
trap "pkill -P $$; exit 1" SIGINT SIGTERM
wait