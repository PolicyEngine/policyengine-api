#!/usr/bin/env bash
set -euo pipefail
# pytest-xdist runs the tests in two workers.
uv run --frozen coverage run -m pytest -n 2 tests
uv run --locked python -m unittest discover -s tests
