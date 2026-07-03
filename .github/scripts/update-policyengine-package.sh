#!/usr/bin/env bash
#
# Update the policyengine[models] pin to a released PolicyEngine .py version,
# refresh uv.lock, derive bundled package versions, create a changelog
# fragment, and open a single-version PR on branch
# auto/update-policyengine-bundle-<version>.
#
# Environment:
#   GH_TOKEN must be set for gh.
#   LATEST_OVERRIDE may be set to target an exact version (the
#     repository_dispatch trigger passes the just-released version here);
#     otherwise the latest version on PyPI is used.
#   FORCE=1 allows targeting a version that is not newer than the current pin.
set -euo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

create_pr_body() {
  cat <<EOF
## Summary

Update PolicyEngine .py bundle from ${CURRENT} to ${LATEST}.

## Bundled versions

- policyengine: ${POLICYENGINE_VERSION:-resolved during update}
- policyengine-core: ${POLICYENGINE_CORE_VERSION:-resolved during update}
- policyengine-us: ${US_VERSION:-resolved during update}
- policyengine-uk: ${UK_VERSION:-resolved during update}

---
Generated automatically by GitHub Actions
EOF
}

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

if [[ "$(printf '%s\n%s\n' "$CURRENT" "$LATEST" | sort -V | tail -n1)" != "$LATEST" && "${FORCE:-0}" != "1" ]]; then
  echo "Requested ${LATEST} is not newer than current ${CURRENT}. Skipping (set FORCE=1 to override)."
  exit 0
fi

BRANCH="auto/update-policyengine-bundle-${LATEST}"

if [[ "$DRY_RUN" == "1" ]]; then
  if git ls-remote --exit-code --heads origin "$BRANCH" &>/dev/null; then
    echo "Dry run: remote branch '${BRANCH}' already exists; would ensure a PR exists for it."
    exit 0
  fi
  echo "Dry run complete. Would update PolicyEngine .py bundle from ${CURRENT} to ${LATEST}."
  echo "Would update pyproject.toml, refresh uv.lock, create a changelog fragment, and open branch '${BRANCH}'."
  exit 0
fi

EXISTING_PR=$(gh pr list \
  --head "$BRANCH" \
  --state open \
  --json number \
  --jq '.[0].number' 2>/dev/null || true)
if [[ -n "$EXISTING_PR" ]]; then
  echo "PR #${EXISTING_PR} already exists for ${BRANCH}. Skipping."
  exit 0
fi

if git ls-remote --exit-code --heads origin "$BRANCH" &>/dev/null; then
  echo "Remote branch '${BRANCH}' already exists without an open PR. Creating PR."
  gh pr create \
    --base master \
    --head "$BRANCH" \
    --title "Update PolicyEngine bundle to ${LATEST}" \
    --body "$(create_pr_body)"
  echo "PR created for existing branch ${BRANCH}"
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

# The PyPI Simple index (which uv resolves from) can lag the JSON API right
# after a release, so retry the lock a few times.
for attempt in 1 2 3; do
  if uv lock --upgrade-package policyengine; then
    break
  fi
  if [[ "$attempt" == "3" ]]; then
    echo "ERROR: uv lock failed after ${attempt} attempts." >&2
    exit 1
  fi
  echo "uv lock attempt ${attempt} failed; retrying in 30s..."
  sleep 30
done

VERSIONS_OUTPUT=$(uv run python .github/find-api-model-versions.py --shell)
eval "$VERSIONS_OUTPUT"

FRAGMENT="changelog.d/update-policyengine-bundle-${LATEST}.changed.md"
echo "Update the PolicyEngine bundle to ${LATEST}." > "$FRAGMENT"

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

git checkout -b "$BRANCH"
git add pyproject.toml uv.lock "$FRAGMENT"

git commit -m "Update PolicyEngine bundle to ${LATEST}"
git push -u origin "$BRANCH"

gh pr create \
  --base master \
  --title "Update PolicyEngine bundle to ${LATEST}" \
  --body "$(create_pr_body)"

echo "PR created: PolicyEngine bundle ${CURRENT} -> ${LATEST}"
