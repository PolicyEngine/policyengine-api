#!/usr/bin/env bash
# Proof fixture: the same script, quoted. shellcheck must accept it.

set -euo pipefail

target="${1:?target directory is required}"
rm -rf "${target}/build"
