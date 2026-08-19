#!/bin/sh
set -eu

PORT="${PORT:-8080}"

exec python3 -m policyengine_api.app_engine_runtime
