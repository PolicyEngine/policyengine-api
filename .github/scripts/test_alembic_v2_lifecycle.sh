#!/usr/bin/env bash

set -euo pipefail

uv run --frozen --extra dev pytest -q \
  tests/unit/v2/test_alembic_v2.py \
  tests/integration/test_alembic_v2_lifecycle.py \
  tests/integration/test_alembic_v2_catalog_tables.py \
  tests/integration/test_alembic_v2_simulation_runs.py \
  tests/integration/test_alembic_v2_saved_item_keys.py \
  tests/integration/test_alembic_v2_user_types.py \
  tests/integration/test_alembic_v2_shared_report_keys.py
