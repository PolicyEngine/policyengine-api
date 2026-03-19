#!/usr/bin/env bash
#
# Create or update a PR for country package updates.
#
# Reads pr_summary.md and creates a new PR (or updates an existing one)
# on the given branch.
#
# Usage: ./create_pr.sh <branch-name>
#
# Environment: GH_TOKEN must be set for the gh CLI.
set -euo pipefail

BRANCH="${1:?Usage: create_pr.sh <branch-name>}"

if [[ ! -f pr_summary.md ]]; then
  echo "Error: pr_summary.md not found"
  exit 1
fi

PR_SUMMARY=$(cat pr_summary.md)

PR_BODY="## Summary

Automated country-package version bump.

## Version Updates

${PR_SUMMARY}

---
Generated automatically by GitHub Actions"

# Re-use an existing PR on this branch if one is open
EXISTING_PR=$(gh pr list --head "$BRANCH" --json number --jq '.[0].number' 2>/dev/null || true)

if [[ -n "$EXISTING_PR" ]]; then
  echo "Updating existing PR #${EXISTING_PR}"
  gh api --method PATCH "/repos/{owner}/{repo}/pulls/${EXISTING_PR}" \
    -f body="$PR_BODY"
else
  echo "Creating new PR"
  gh pr create \
    --title "Update country packages" \
    --body "$PR_BODY" \
    --base master
fi
