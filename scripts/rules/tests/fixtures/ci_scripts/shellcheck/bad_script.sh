#!/usr/bin/env bash
# Proof fixture: an unquoted variable (SC2086). shellcheck must reject it.

set -euo pipefail

target=$1
rm -rf $target/build
