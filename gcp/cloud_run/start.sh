#!/bin/sh
set -eu

PORT="${PORT:-8080}"
CACHE_REDIS_HOST="${CACHE_REDIS_HOST:-127.0.0.1}"
CACHE_REDIS_PORT="${CACHE_REDIS_PORT:-6379}"
CACHE_REDIS_DB="${CACHE_REDIS_DB:-0}"
WEB_CONCURRENCY="${WEB_CONCURRENCY:-1}"
export CACHE_REDIS_HOST CACHE_REDIS_PORT CACHE_REDIS_DB

redis-server --bind "$CACHE_REDIS_HOST" \
             --port "$CACHE_REDIS_PORT" \
             --protected-mode yes \
             --maxclients 10000 \
             --timeout 0 &

until redis-cli -h "$CACHE_REDIS_HOST" -p "$CACHE_REDIS_PORT" ping >/dev/null 2>&1; do
  sleep 1
done

uvicorn policyengine_api.asgi:app \
  --host 0.0.0.0 \
  --port "$PORT" \
  --workers "$WEB_CONCURRENCY" \
  --proxy-headers \
  --forwarded-allow-ips '*' &

trap "pkill -P $$; exit 1" INT TERM

wait
