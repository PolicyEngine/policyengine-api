#!/usr/bin/env bash
set -euo pipefail

# Run from the environment uv.lock defines (make install), which includes
# pytest-xdist for the workers.
#
# One pytest worker per test: each test waits on its own requests to the
# staging candidate and the simulation API, so the step takes about as long as
# the longest test. A new test here needs -n raised with it. The candidate is
# one Cloud Run instance that admits 6 requests at a time (cloud_run_env.sh).
# Each test sends one request at a time, so at most 3 requests wait at the
# Cloud Run front end for a free slot: Cloud Run holds them for the longer of
# 10 seconds and 3.5 times the average instance startup time, and the tests'
# client allows each request 90 seconds. Before adding a test, check the
# candidate can take one more.
uv run --frozen --extra dev python -m pytest \
  -n 9 \
  --dist load \
  --maxschedchunk=1 \
  tests/integration/test_live_budget_window_cache.py \
  tests/integration/test_live_calculate.py \
  tests/integration/test_live_economy.py \
  -v
