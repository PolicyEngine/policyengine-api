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

# The household calculation checks run afterwards, on 4 workers, so they never
# share the candidate with the tests above. They call the simulation service's
# household calculation route, so they pass only once that route is deployed
# to staging; staging promotion waits on them, so the change that adds them
# merges only after that deployment. Their requests are short (a
# submission, then a poll every few seconds) apart from the parity tests'
# /calculate requests, but the parallel check submits 6 calculations at once:
# with the 3 other workers' requests, at most 3 wait for a free slot, as above.
uv run --frozen --extra dev python -m pytest \
  -n 4 \
  --dist load \
  --maxschedchunk=1 \
  tests/integration/test_live_v2_household_calculations.py \
  tests/integration/test_live_v2_household_parity.py \
  -v
