#!/usr/bin/env bash
set -euo pipefail
upgrade_arguments=(--upgrade-package requests)
uv lock "${upgrade_arguments[@]}"
