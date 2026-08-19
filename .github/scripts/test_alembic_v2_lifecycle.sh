#!/usr/bin/env bash

set -euo pipefail

uv run pytest -q \
  tests/unit/v2/test_alembic_v2.py \
  tests/integration/test_alembic_v2_lifecycle.py
