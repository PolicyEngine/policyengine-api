#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8080}"
WEB_CONCURRENCY="${WEB_CONCURRENCY:-1}"

# gunicorn's master binds the listen socket before forking workers, so the
# Cloud Run TCP startup probe passes immediately instead of racing the
# multi-minute app import (which happens in the worker, post-fork, because
# application preloading is disabled). --timeout 0 is required: a worker mid-import does
# not heartbeat, and the default 30s watchdog would kill it before boot.
exec gunicorn policyengine_api.asgi:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers "$WEB_CONCURRENCY" \
  --bind "0.0.0.0:${PORT}" \
  --timeout 0 \
  --keep-alive 5 \
  --forwarded-allow-ips '*'
