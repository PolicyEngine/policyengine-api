#!/usr/bin/env bash

set -euo pipefail

: "${POLICYENGINE_DB_INSTANCE_CONNECTION_NAME:?POLICYENGINE_DB_INSTANCE_CONNECTION_NAME is required}"

proxy_version="2.25.0"
proxy_sha256="091a9a12eddab6c028b6c563a4f2dacd067e8f7689c25a3fb4afce397e1f0c60"
proxy_path="${RUNNER_TEMP:-/tmp}/cloud-sql-proxy"
pid_path="${RUNNER_TEMP:-/tmp}/cloud-sql-proxy.pid"
log_path="${RUNNER_TEMP:-/tmp}/cloud-sql-proxy.log"

curl -fsSL \
  "https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v${proxy_version}/cloud-sql-proxy.linux.amd64" \
  --output "${proxy_path}"
printf '%s  %s\n' "${proxy_sha256}" "${proxy_path}" | sha256sum --check --status
chmod +x "${proxy_path}"

"${proxy_path}" \
  --quota-project policyengine-api \
  --address 127.0.0.1 \
  --port 3307 \
  "${POLICYENGINE_DB_INSTANCE_CONNECTION_NAME}" \
  >"${log_path}" 2>&1 &
proxy_pid="$!"
printf '%s\n' "${proxy_pid}" >"${pid_path}"

for _ in $(seq 1 30); do
  if ! kill -0 "${proxy_pid}" 2>/dev/null; then
    echo "Cloud SQL Auth Proxy exited before becoming ready." >&2
    sed -n '1,120p' "${log_path}" >&2
    exit 1
  fi
  if python -c 'import socket; socket.create_connection(("127.0.0.1", 3307), 1).close()' 2>/dev/null; then
    exit 0
  fi
  sleep 1
done

echo "Cloud SQL Auth Proxy did not become ready." >&2
exit 1
