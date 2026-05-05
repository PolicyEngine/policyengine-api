#!/bin/sh
# Environment variables
PORT="${PORT:-8080}"
CACHE_REDIS_HOST="${CACHE_REDIS_HOST:-127.0.0.1}"
CACHE_REDIS_PORT="${CACHE_REDIS_PORT:-6379}"
CACHE_REDIS_DB="${CACHE_REDIS_DB:-0}"
export CACHE_REDIS_HOST CACHE_REDIS_PORT CACHE_REDIS_DB

# Start Redis with configuration for multiple clients.
redis-server --bind "$CACHE_REDIS_HOST" \
             --port "$CACHE_REDIS_PORT" \
             --protected-mode yes \
             --maxclients 10000 \
             --timeout 0 &

# Wait for Redis to be ready
until redis-cli -h "$CACHE_REDIS_HOST" -p "$CACHE_REDIS_PORT" ping >/dev/null 2>&1; do
  sleep 1
done

# Start the API
gunicorn -b :"$PORT" policyengine_api.api --timeout 300 --workers 5 --preload &

# Keep the script running and handle shutdown gracefully
trap "pkill -P $$; exit 1" INT TERM

wait
