#!/usr/bin/env bash

# Install the ruff version pinned in uv.lock, so CI formats and lints with the
# same ruff as `uv sync --extra dev`.
#
# Usage: install_locked_ruff.sh [path/to/uv.lock]
# PYTHON selects the interpreter that reads the lock (Python 3.11+ for tomllib).

set -euo pipefail

lock_file="${1:-uv.lock}"
python_bin="${PYTHON:-python3}"

version="$(
  "${python_bin}" - "${lock_file}" <<'PY'
import sys
import tomllib

lock_path = sys.argv[1]
with open(lock_path, "rb") as lock:
    packages = tomllib.load(lock).get("package", [])
versions = [package["version"] for package in packages if package.get("name") == "ruff"]
if not versions:
    sys.exit(f"ruff is not pinned in {lock_path}; add it to the dev extra and run uv lock")
print(versions[0])
PY
)"

pip install "ruff==${version}"
ruff --version
