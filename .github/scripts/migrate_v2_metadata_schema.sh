#!/usr/bin/env bash

set -euo pipefail
set +x

uv run alembic -c alembic-v2.ini upgrade head
uv run alembic -c alembic-v2.ini current --check-heads
uv run alembic -c alembic-v2.ini check
