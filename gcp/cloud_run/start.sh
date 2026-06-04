#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8080}"
CACHE_REDIS_HOST="${CACHE_REDIS_HOST:-127.0.0.1}"
CACHE_REDIS_PORT="${CACHE_REDIS_PORT:-6379}"
CACHE_REDIS_DB="${CACHE_REDIS_DB:-0}"
WEB_CONCURRENCY="${WEB_CONCURRENCY:-1}"
REDIS_READY_MAX_ATTEMPTS="${REDIS_READY_MAX_ATTEMPTS:-30}"
export CACHE_REDIS_HOST CACHE_REDIS_PORT CACHE_REDIS_DB

redis_pid=""
uvicorn_pid=""

shutdown() {
  trap - INT TERM

  if [ -n "$uvicorn_pid" ] && kill -0 "$uvicorn_pid" 2>/dev/null; then
    kill "$uvicorn_pid" 2>/dev/null || true
  fi

  if [ -n "$redis_pid" ] && kill -0 "$redis_pid" 2>/dev/null; then
    kill "$redis_pid" 2>/dev/null || true
  fi

  if [ -n "$uvicorn_pid" ]; then
    wait "$uvicorn_pid" 2>/dev/null || true
  fi

  if [ -n "$redis_pid" ]; then
    wait "$redis_pid" 2>/dev/null || true
  fi
}

trap 'shutdown; exit 143' INT TERM

redis-server --bind "$CACHE_REDIS_HOST" \
             --port "$CACHE_REDIS_PORT" \
             --protected-mode yes \
             --maxclients 10000 \
             --timeout 0 &
redis_pid="$!"

redis_ready_attempts=0
until redis-cli -h "$CACHE_REDIS_HOST" -p "$CACHE_REDIS_PORT" ping >/dev/null 2>&1; do
  redis_ready_attempts=$((redis_ready_attempts + 1))
  if ! kill -0 "$redis_pid" 2>/dev/null; then
    echo "Redis exited before becoming ready" >&2
    shutdown
    exit 1
  fi

  if [ "$redis_ready_attempts" -ge "$REDIS_READY_MAX_ATTEMPTS" ]; then
    echo "Redis did not become ready after $redis_ready_attempts attempts" >&2
    shutdown
    exit 1
  fi
  sleep 1
done

uvicorn policyengine_api.asgi:app \
  --host 0.0.0.0 \
  --port "$PORT" \
  --workers "$WEB_CONCURRENCY" \
  --proxy-headers \
  --forwarded-allow-ips '*' &
uvicorn_pid="$!"

set +e
wait -n "$redis_pid" "$uvicorn_pid"
status="$?"
set -e

if ! kill -0 "$redis_pid" 2>/dev/null; then
  echo "Redis exited; stopping Cloud Run container" >&2
elif ! kill -0 "$uvicorn_pid" 2>/dev/null; then
  echo "Uvicorn exited; stopping Cloud Run container" >&2
else
  echo "A supervised Cloud Run process exited; stopping container" >&2
fi

shutdown

if [ "$status" -eq 0 ]; then
  exit 1
fi

exit "$status"
