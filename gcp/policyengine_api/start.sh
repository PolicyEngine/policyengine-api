#!/bin/sh
# Environment variables
PORT="${PORT:-8080}"
REDIS_PORT="${REDIS_PORT:-6379}"

# Start the API
gunicorn -b :"$PORT" policyengine_api.api --timeout 300 --workers 5 --preload &

# Start Redis with configuration for multiple clients
redis-server --protected-mode no \
             --maxclients 10000 \
             --timeout 0 &

# Wait for Redis to be ready
sleep 2

# Keep the script running and handle shutdown gracefully
trap "pkill -P $$; exit 1" INT TERM

wait
