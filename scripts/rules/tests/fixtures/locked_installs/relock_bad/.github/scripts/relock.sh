#!/usr/bin/env bash
set -euo pipefail
uv lock --upgrade
gh pr create --title "Relock" --body "Relock"
