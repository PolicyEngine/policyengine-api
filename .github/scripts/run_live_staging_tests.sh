#!/usr/bin/env bash
set -euo pipefail

python -m pytest \
  -n 2 \
  --dist load \
  --maxschedchunk=1 \
  tests/integration/test_live_budget_window_cache.py \
  tests/integration/test_live_calculate.py \
  tests/integration/test_live_economy.py \
  -v
