#!/usr/bin/env bash

# Relock uv.lock: upgrade every locked package to the newest version that
# pyproject.toml allows, except the PolicyEngine .py bundle (policyengine) and
# the packages its extras pin, which change only through the bundle update
# workflow. Then check the lock, and fail if a held package moved anyway.
#
# Run from the repository root. uv resolves the lock for every Python version
# that requires-python allows, whichever interpreter runs it; the interpreter
# only builds packages that publish no static metadata.
#
# Environment:
#   RELOCK_PYTHON        Python version uv runs with (default: 3.12, the
#                        version the Public API runs on; .python-version names
#                        a newer one)
#   RELOCK_SUMMARY_FILE  where to write the Markdown summary of the version
#                        changes (default: relock-summary.md)
#   GITHUB_OUTPUT        when set, receives changed=true or changed=false
#   PYTHON               interpreter that reads the lock (Python 3.11+ for
#                        tomllib; default: python3)

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
locked_packages=("${PYTHON:-python3}" "${script_dir}/locked_packages.py")
python_version="${RELOCK_PYTHON:-3.12}"
summary_file="${RELOCK_SUMMARY_FILE:-relock-summary.md}"

upgradeable="$("${locked_packages[@]}" upgradeable uv.lock)"
held_before="$("${locked_packages[@]}" held uv.lock)"
if [[ -z "${upgradeable}" ]]; then
  echo "uv.lock has no packages to upgrade." >&2
  exit 1
fi

upgrade_arguments=()
while IFS= read -r package_name; do
  upgrade_arguments+=(--upgrade-package "${package_name}")
done <<<"${upgradeable}"

previous_lock="$(mktemp)"
trap 'rm -f "${previous_lock}"' EXIT
cp uv.lock "${previous_lock}"

uv lock --python "${python_version}" "${upgrade_arguments[@]}"
uv lock --check --python "${python_version}"

held_after="$("${locked_packages[@]}" held uv.lock)"
if [[ "${held_after}" != "${held_before}" ]]; then
  {
    echo "::error::The relock moved packages that only the bundle update workflow may change."
    echo "Before:"
    echo "${held_before}"
    echo "After:"
    echo "${held_after}"
  } >&2
  exit 1
fi

if cmp -s "${previous_lock}" uv.lock; then
  echo "uv.lock is unchanged; nothing to propose."
  changed=false
else
  "${locked_packages[@]}" summary "${previous_lock}" uv.lock >"${summary_file}"
  cat "${summary_file}"
  changed=true
fi

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  echo "changed=${changed}" >>"${GITHUB_OUTPUT}"
fi
