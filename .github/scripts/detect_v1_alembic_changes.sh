#!/usr/bin/env bash

set -euo pipefail

: "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"

if [[ "$#" -ne 2 ]]; then
  echo "usage: detect_v1_alembic_changes.sh BASE HEAD" >&2
  exit 2
fi

python scripts/v1_alembic_changes.py "$1" "$2" >>"${GITHUB_OUTPUT}"
