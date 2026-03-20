#!/usr/bin/env bash
#
# Check if a country package has a newer version on PyPI than what is
# pinned in pyproject.toml. If so, update the pin, create a changelog
# fragment, and open a version-specific PR.
#
# Usage: ./update-package.sh <package-name>
#   e.g. ./update-package.sh policyengine-us
#
# Requires: curl, jq, sed, git, gh (GitHub CLI), python3 + requests
# Environment: GH_TOKEN must be set for the gh CLI.
set -euo pipefail

PACKAGE="${1:?Usage: update-package.sh <package-name>}"

# Derive the underscore form used in pyproject.toml
# (policyengine-us -> policyengine_us)
PACKAGE_UNDERSCORE="${PACKAGE//-/_}"

# Derive human-readable display name
# (policyengine-us -> PolicyEngine US)
COUNTRY="${PACKAGE#policyengine-}"
COUNTRY_UPPER=$(echo "$COUNTRY" | tr '[:lower:]' '[:upper:]')
DISPLAY_NAME="PolicyEngine ${COUNTRY_UPPER}"

# ---------------------------------------------------------------------------
# 1. Read current pinned version from pyproject.toml
# ---------------------------------------------------------------------------
CURRENT=$(grep -oP "(?<=${PACKAGE_UNDERSCORE}==)[0-9]+\.[0-9]+\.[0-9]+" pyproject.toml || true)
if [[ -z "$CURRENT" ]]; then
  echo "Package '${PACKAGE_UNDERSCORE}' not found in pyproject.toml. Skipping."
  exit 0
fi
echo "Current version: ${PACKAGE_UNDERSCORE}==${CURRENT}"

# ---------------------------------------------------------------------------
# 2. Fetch latest version from PyPI
# ---------------------------------------------------------------------------
LATEST=$(curl -sf "https://pypi.org/pypi/${PACKAGE}/json" | jq -r .info.version)
if [[ -z "$LATEST" || "$LATEST" == "null" ]]; then
  echo "Could not fetch latest version for '${PACKAGE}' from PyPI."
  exit 1
fi
echo "Latest version:  ${PACKAGE}==${LATEST}"

# ---------------------------------------------------------------------------
# 3. Compare — exit early if already up to date
# ---------------------------------------------------------------------------
if [[ "$CURRENT" == "$LATEST" ]]; then
  echo "Already up to date. Nothing to do."
  exit 0
fi
echo "Update available: ${CURRENT} -> ${LATEST}"

# ---------------------------------------------------------------------------
# 4. Check if a branch for this exact version already exists
# ---------------------------------------------------------------------------
BRANCH="auto/update-${PACKAGE}-${LATEST}"

if git ls-remote --exit-code --heads origin "$BRANCH" &>/dev/null; then
  echo "Branch '${BRANCH}' already exists on remote. Skipping."
  exit 0
fi

# ---------------------------------------------------------------------------
# 5. Update version pin in pyproject.toml
# ---------------------------------------------------------------------------
sed -i "s/${PACKAGE_UNDERSCORE}==${CURRENT}/${PACKAGE_UNDERSCORE}==${LATEST}/" pyproject.toml

if git diff --quiet pyproject.toml; then
  echo "No changes to pyproject.toml after substitution. Skipping."
  exit 0
fi

# ---------------------------------------------------------------------------
# 6. Create changelog fragment (required by PR CI)
# ---------------------------------------------------------------------------
FRAGMENT="changelog.d/update-${PACKAGE}-${LATEST}.changed.md"
echo "Update ${DISPLAY_NAME} to ${LATEST}." > "$FRAGMENT"

# ---------------------------------------------------------------------------
# 7. Fetch upstream changelog for the PR body
# ---------------------------------------------------------------------------
CHANGELOG=$(python3 .github/scripts/check_updates.py \
  --package "$PACKAGE" \
  --old-version "$CURRENT" \
  --new-version "$LATEST" 2>/dev/null || echo "")

PR_BODY="## Summary

Update ${DISPLAY_NAME} from ${CURRENT} to ${LATEST}."

if [[ -n "$CHANGELOG" ]]; then
  PR_BODY="${PR_BODY}

## What changed (${CURRENT} -> ${LATEST})

${CHANGELOG}"
fi

PR_BODY="${PR_BODY}

---
Generated automatically by GitHub Actions"

# ---------------------------------------------------------------------------
# 8. Commit, push (no force), and open PR
# ---------------------------------------------------------------------------
git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

git checkout -b "$BRANCH"
git add pyproject.toml "$FRAGMENT"
git commit -m "Update ${DISPLAY_NAME} to ${LATEST}"
git push -u origin "$BRANCH"

gh pr create \
  --base master \
  --title "Update ${DISPLAY_NAME} to ${LATEST}" \
  --body "$PR_BODY"

echo "PR created: ${DISPLAY_NAME} ${CURRENT} -> ${LATEST}"
