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
server_pid=""

shutdown() {
  trap - INT TERM

  if [ -n "$server_pid" ] && kill -0 "$server_pid" 2>/dev/null; then
    kill "$server_pid" 2>/dev/null || true
  fi

  if [ -n "$redis_pid" ] && kill -0 "$redis_pid" 2>/dev/null; then
    kill "$redis_pid" 2>/dev/null || true
  fi

  if [ -n "$server_pid" ]; then
    wait "$server_pid" 2>/dev/null || true
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

# gunicorn's master binds the listen socket before forking workers, so the
# Cloud Run TCP startup probe passes immediately instead of racing the
# multi-minute app import (which happens in the worker, post-fork, because
# --preload is NOT set). --timeout 0 is required: a worker mid-import does
# not heartbeat, and the default 30s watchdog would kill it before boot.
gunicorn policyengine_api.asgi:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers "$WEB_CONCURRENCY" \
  --bind "0.0.0.0:${PORT}" \
  --timeout 0 \
  --keep-alive 5 \
  --forwarded-allow-ips '*' &
server_pid="$!"

set +e
wait -n "$redis_pid" "$server_pid"
status="$?"
set -e

if ! kill -0 "$redis_pid" 2>/dev/null; then
  echo "Redis exited; stopping Cloud Run container" >&2
elif ! kill -0 "$server_pid" 2>/dev/null; then
  echo "API server exited; stopping Cloud Run container" >&2
else
  echo "A supervised Cloud Run process exited; stopping container" >&2
fi

shutdown

if [ "$status" -eq 0 ]; then
  exit 1
fi

exit "$status"
