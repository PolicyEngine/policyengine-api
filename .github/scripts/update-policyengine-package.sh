#!/usr/bin/env bash
#
# Check whether PolicyEngine .py has a newer release on PyPI. If so, update the
# policyengine[models] pin, refresh uv.lock, derive bundled package versions,
# create a changelog fragment, and open a PR.
#
# Environment:
#   GH_TOKEN must be set for gh.
#   LATEST_OVERRIDE may be set for testing a specific version.
set -euo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

CURRENT=$(python3 -c '
import re
from pathlib import Path

match = re.search(r"policyengine\[models\]==([0-9]+\.[0-9]+\.[0-9]+)", Path("pyproject.toml").read_text())
print(match.group(1) if match else "")
')
if [[ -z "$CURRENT" ]]; then
  echo "policyengine[models] pin not found in pyproject.toml"
  exit 1
fi
echo "Current PolicyEngine bundle: ${CURRENT}"

if [[ -n "${LATEST_OVERRIDE:-}" ]]; then
  LATEST="$LATEST_OVERRIDE"
else
  LATEST=$(python3 -c '
import requests

response = requests.get("https://pypi.org/pypi/policyengine/json", timeout=30)
response.raise_for_status()
print(response.json()["info"]["version"])
')
fi
echo "Latest PolicyEngine bundle:  ${LATEST}"

if [[ "$CURRENT" == "$LATEST" ]]; then
  echo "Already up to date. Nothing to do."
  exit 0
fi

BRANCH="auto/update-policyengine-bundle-${LATEST}"
if git ls-remote --exit-code --heads origin "$BRANCH" &>/dev/null; then
  echo "Branch '${BRANCH}' already exists on remote. Skipping."
  exit 0
fi

if [[ "$DRY_RUN" == "1" ]]; then
  echo "Dry run complete. Would update PolicyEngine .py bundle from ${CURRENT} to ${LATEST}."
  echo "Would update pyproject.toml, refresh uv.lock, create a changelog fragment, and open branch '${BRANCH}'."
  exit 0
fi

python3 -c '
import re
import sys
from pathlib import Path

current, latest = sys.argv[1], sys.argv[2]
path = Path("pyproject.toml")
text = path.read_text()
updated = re.sub(
    rf"policyengine\[models\]=={re.escape(current)}",
    f"policyengine[models]=={latest}",
    text,
    count=1,
)
if updated == text:
    raise SystemExit("No policyengine[models] pin changed")
path.write_text(updated)
' "$CURRENT" "$LATEST"

uv lock --upgrade-package policyengine

VERSIONS_OUTPUT=$(uv run python .github/find-api-model-versions.py --shell)
eval "$VERSIONS_OUTPUT"

FRAGMENT="changelog.d/update-policyengine-bundle-${LATEST}.changed.md"
echo "Update the PolicyEngine bundle to ${LATEST}." > "$FRAGMENT"

PR_BODY="## Summary

Update PolicyEngine .py bundle from ${CURRENT} to ${LATEST}.

## Bundled versions

- policyengine: ${POLICYENGINE_VERSION}
- policyengine-core: ${POLICYENGINE_CORE_VERSION}
- policyengine-us: ${US_VERSION}
- policyengine-uk: ${UK_VERSION}

---
Generated automatically by GitHub Actions"

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

git checkout -b "$BRANCH"
git add pyproject.toml uv.lock "$FRAGMENT"

git commit -m "Update PolicyEngine bundle to ${LATEST}"
git push -u origin "$BRANCH"

gh pr create \
  --base master \
  --title "Update PolicyEngine bundle to ${LATEST}" \
  --body "$PR_BODY"

echo "PR created: PolicyEngine bundle ${CURRENT} -> ${LATEST}"
