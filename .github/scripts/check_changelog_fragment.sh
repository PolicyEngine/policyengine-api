#!/usr/bin/env bash

set -euo pipefail

fragments="$(find changelog.d -type f ! -name '.gitkeep' | wc -l)"
if [[ "${fragments}" -eq 0 ]]; then
  echo "::error::No changelog fragment found in changelog.d/"
  echo "Add one with: echo 'Description.' > changelog.d/\$(git branch --show-current).<type>.md"
  echo "Types: added, changed, fixed, removed, breaking"
  exit 1
fi
