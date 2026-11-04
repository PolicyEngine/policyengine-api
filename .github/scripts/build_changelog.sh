#!/usr/bin/env bash

# Build the changelog for the version in pyproject.toml with towncrier.
# Run from the repository root, after .github/bump_version.py and uv lock.

set -euo pipefail

version="$(
  python - <<'PY'
import re

match = re.search(r'version = "(.+?)"', open("pyproject.toml").read())
if match is None:
    raise SystemExit("no version found in pyproject.toml")
print(match.group(1))
PY
)"

# towncrier comes from the dev extra in uv.lock, which uv lock has just
# refreshed with the new project version.
uv run --frozen --extra dev towncrier build --yes --version "${version}"
