#!/usr/bin/env bash

set -euo pipefail

pid_path="${RUNNER_TEMP:-/tmp}/cloud-sql-proxy.pid"
if [[ ! -f "${pid_path}" ]]; then
  exit 0
fi

proxy_pid="$(cat "${pid_path}")"
if kill -0 "${proxy_pid}" 2>/dev/null; then
  kill "${proxy_pid}"
  wait "${proxy_pid}" 2>/dev/null || true
fi
