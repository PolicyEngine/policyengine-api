#!/usr/bin/env bash
#
# Update the policyengine[models] pin to a released PolicyEngine .py version,
# synchronize the generic image pin, refresh uv.lock, derive bundled package versions, create a changelog
# fragment, and open a single-version PR on branch
# auto/update-policyengine-bundle-<version>.
#
# Every PR names its tracking issue on the first line of its description
# (rule api.process.pr-tracking-issue): the oldest open issue titled
# "Update PolicyEngine bundle to <version>", or a new one when none is open.
# Merging the PR closes it.
#
# Environment:
#   GH_TOKEN must be set for gh: a token that can write issues and pull
#     requests.
#   GITHUB_REPOSITORY is owner/name of the repository the tracking issue is in
#     (set by the runner; default: PolicyEngine/policyengine-api).
#   LATEST_OVERRIDE may be set to target an exact version (the
#     repository_dispatch trigger passes the just-released version here);
#     otherwise the latest version on PyPI is used.
#   FORCE=1 allows targeting a version that is not newer than the current pin.
#   LOCK_RETRY_SECONDS controls the pause between lock retries (default: 30).
set -euo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

REPOSITORY="${GITHUB_REPOSITORY:-PolicyEngine/policyengine-api}"
ISSUE_NUMBER=""

# Set ISSUE_NUMBER to the oldest open tracking issue for LATEST, opening one
# when none is open. This sets a variable rather than printing, because bash
# turns off set -e inside $(...), and a failed lookup must not open a
# duplicate issue.
find_or_open_tracking_issue() {
  local title="Update PolicyEngine bundle to ${LATEST}"
  local issue_number
  local issue_url

  issue_number="$(
    gh issue list \
      --repo "${REPOSITORY}" \
      --state open \
      --limit 1000 \
      --json number,title \
      --jq "map(select(.title == \"${title}\")) | sort_by(.number) | .[0].number // empty"
  )"
  if [[ -z "${issue_number}" ]]; then
    issue_url="$(
      gh issue create \
        --repo "${REPOSITORY}" \
        --title "${title}" \
        --body "Tracks the automated update of the PolicyEngine .py bundle to ${LATEST} by .github/workflows/update-policyengine-bundle.yaml. The update pull request names this issue on the first line of its description and closes it when it merges."
    )"
    issue_number="${issue_url##*/}"
  fi

  if [[ ! "${issue_number}" =~ ^[0-9]+$ ]]; then
    echo "Could not resolve the tracking issue for PolicyEngine bundle ${LATEST}: ${issue_number}" >&2
    exit 1
  fi
  ISSUE_NUMBER="${issue_number}"
}

create_pr_body() {
  cat <<EOF
Fixes #${ISSUE_NUMBER}

## Summary

Update PolicyEngine .py bundle from ${CURRENT} to ${LATEST}.

## Bundled versions

- policyengine: ${POLICYENGINE_VERSION:-resolved during update}
- policyengine-core: ${POLICYENGINE_CORE_VERSION:-resolved during update}
- policyengine-us: ${US_VERSION:-resolved during update}
- policyengine-uk: ${UK_VERSION:-resolved during update}
- spm-calculator: ${SPM_CALCULATOR_VERSION:-resolved during update}

## Certified data releases

- US: ${US_DATA_VERSION:-resolved during update}
- UK: ${UK_DATA_VERSION:-resolved during update}

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
  echo "Would update pyproject.toml and docker/Dockerfile, refresh uv.lock, create a changelog fragment, and open branch '${BRANCH}'."
  exit 0
fi

EXISTING_PR=$(gh pr view "$BRANCH" \
  --json number,state \
  --jq 'select(.state == "OPEN") | .number' 2>/dev/null || true)
if [[ -n "$EXISTING_PR" ]]; then
  echo "PR #${EXISTING_PR} already exists for ${BRANCH}. Skipping."
  exit 0
fi

if git ls-remote --exit-code --heads origin "$BRANCH" &>/dev/null; then
  echo "Remote branch '${BRANCH}' already exists without an open PR. Creating PR."
  find_or_open_tracking_issue
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
updates = {}
for name in ("pyproject.toml", "docker/Dockerfile"):
    path = Path(name)
    text = path.read_text()
    updated, count = re.subn(
        rf"policyengine\[models\]=={re.escape(current)}(?![0-9A-Za-z.+-])",
        f"policyengine[models]=={latest}",
        text,
    )
    if count != 1:
        raise SystemExit(f"Expected one matching policyengine[models] pin in {name}")
    updates[path] = updated
# Validate both inputs before changing either file.
for path, updated in updates.items():
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
  echo "uv lock attempt ${attempt} failed; retrying in ${LOCK_RETRY_SECONDS:-30}s..."
  sleep "${LOCK_RETRY_SECONDS:-30}"
done

uv lock --check

VERSIONS_OUTPUT=$(uv run --frozen python .github/find-api-model-versions.py --shell)
eval "$VERSIONS_OUTPUT"

if [[ "$POLICYENGINE_VERSION" != "$LATEST" ]]; then
  echo "Installed PolicyEngine version ${POLICYENGINE_VERSION} does not match requested version ${LATEST}." >&2
  exit 1
fi

FRAGMENT="changelog.d/update-policyengine-bundle-${LATEST}.changed.md"
echo "Update the PolicyEngine bundle to ${LATEST}." > "$FRAGMENT"

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

git checkout -b "$BRANCH"
git add pyproject.toml docker/Dockerfile uv.lock "$FRAGMENT"

git commit -m "Update PolicyEngine bundle to ${LATEST}"
git push -u origin "$BRANCH"

find_or_open_tracking_issue
gh pr create \
  --base master \
  --title "Update PolicyEngine bundle to ${LATEST}" \
  --body "$(create_pr_body)"

echo "PR created: PolicyEngine bundle ${CURRENT} -> ${LATEST}"
