#!/bin/bash
# Environment variables
PORT="${PORT:-8080}"
WORKER_COUNT="${WORKER_COUNT:-3}"
REDIS_PORT="${REDIS_PORT:-6379}"

# Start the API
gunicorn -b :"$PORT" policyengine_api.api --timeout 300 --workers 5 --preload &

# Start multiple workers using POSIX-compliant loop
# TODO worker.py does not seem to exist?
#i=1
#while [ $i -le "$WORKER_COUNT" ]
#do
#    echo "Starting worker $i..."
#    python3 policyengine_api/worker.py &
#    i=$((i + 1))
#done

# Keep the script running and handle shutdown gracefully
trap "pkill -P $$; exit 1" INT TERM

wait
