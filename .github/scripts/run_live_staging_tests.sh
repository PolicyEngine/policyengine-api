#!/usr/bin/env bash
set -euo pipefail

# Run from the environment uv.lock defines (make install), which includes
# pytest-xdist for the two workers.
uv run --frozen --extra dev python -m pytest \
  -n 2 \
  --dist load \
  --maxschedchunk=1 \
  tests/integration/test_live_budget_window_cache.py \
  tests/integration/test_live_calculate.py \
  tests/integration/test_live_economy.py \
  -v
