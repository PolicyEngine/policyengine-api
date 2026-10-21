#!/usr/bin/env bash

# Commit a relocked uv.lock with a changelog fragment, push it to the relock
# branch, and open the relock pull request, or update the open one.
#
# - The branch is rebuilt on every run from the checked-out commit of the base
#   branch, so its diff is always the base branch plus one relock. The push
#   replaces the branch (with a lease on the commit it last saw), and is
#   skipped when the branch already holds the same files.
# - The tracking issue is the oldest open issue titled "Relock dependencies",
#   or a new one when none is open. The first line of the pull request
#   description is "Fixes #N", so merging the pull request closes it and the
#   next relock opens a new one.
# - The description lists the version changes from RELOCK_SUMMARY_FILE.
#
# Run from the repository root, after relock_dependencies.sh reported a change.
#
# Environment:
#   GITHUB_REPOSITORY    owner/name of this repository (set by the runner)
#   GH_TOKEN             read by gh: a token that can write issues and pull
#                        requests. git pushes with the credentials the checkout
#                        stored.
#   RELOCK_SUMMARY_FILE  Markdown summary written by relock_dependencies.sh
#   BASE_BRANCH          branch the pull request merges into (default: master)
#   RELOCK_BRANCH        branch the pull request is opened from
#                        (default: auto/relock-dependencies)

set -euo pipefail

: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${RELOCK_SUMMARY_FILE:?RELOCK_SUMMARY_FILE is required}"
if [[ ! -r "${RELOCK_SUMMARY_FILE}" ]]; then
  echo "Relock summary ${RELOCK_SUMMARY_FILE} is missing or unreadable." >&2
  exit 1
fi

base_branch="${BASE_BRANCH:-master}"
relock_branch="${RELOCK_BRANCH:-auto/relock-dependencies}"
title="Relock dependencies"
fragment="changelog.d/relock-dependencies.changed.md"
issue_body="Tracks the daily relock of uv.lock by .github/workflows/relock-dependencies.yml. The relock pull request names this issue on the first line of its description and closes it when it merges."

# Set ISSUE_NUMBER to the oldest open tracking issue, opening one when none is
# open. This sets a variable rather than printing, because bash turns off
# set -e inside $(...), and a failed lookup must not open a duplicate issue.
find_or_open_tracking_issue() {
  local issue_number
  local issue_url

  issue_number="$(
    gh issue list \
      --repo "${GITHUB_REPOSITORY}" \
      --state open \
      --limit 1000 \
      --json number,title \
      --jq "map(select(.title == \"${title}\")) | sort_by(.number) | .[0].number // empty"
  )"
  if [[ -z "${issue_number}" ]]; then
    issue_url="$(
      gh issue create \
        --repo "${GITHUB_REPOSITORY}" \
        --title "${title}" \
        --body "${issue_body}"
    )"
    issue_number="${issue_url##*/}"
  fi

  if [[ ! "${issue_number}" =~ ^[0-9]+$ ]]; then
    echo "Could not resolve the relock tracking issue: ${issue_number}" >&2
    exit 1
  fi
  ISSUE_NUMBER="${issue_number}"
}

pr_description() {
  cat <<EOF
Fixes #${ISSUE_NUMBER}

## Summary

Automated relock of \`uv.lock\` by \`.github/workflows/relock-dependencies.yml\`, which runs daily. Every locked package is upgraded to the newest version that \`pyproject.toml\` allows, except the PolicyEngine .py bundle and the packages its extras pin. CI on this pull request tests the relocked versions.

Each run rebuilds \`${relock_branch}\` from \`${base_branch}\` and replaces it, so commits pushed to this branch by hand are lost on the next run.

EOF
  cat "${RELOCK_SUMMARY_FILE}"
}

open_pr="$(
  gh pr list \
    --repo "${GITHUB_REPOSITORY}" \
    --base "${base_branch}" \
    --head "${relock_branch}" \
    --state open \
    --json number \
    --jq '.[0].number // empty'
)"
ISSUE_NUMBER=""
find_or_open_tracking_issue

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
echo "Update the locked versions of the Public API's dependencies." >"${fragment}"
git checkout --quiet -B "${relock_branch}"
git add uv.lock "${fragment}"
git commit --quiet -m "Relock dependencies"

remote_commit="$(git ls-remote --heads origin "refs/heads/${relock_branch}" | cut -f1)"
if [[ -n "${remote_commit}" ]]; then
  git fetch --quiet origin "refs/heads/${relock_branch}"
fi
if [[ -n "${remote_commit}" ]] && git diff --quiet "${remote_commit}" HEAD --; then
  echo "${relock_branch} already holds this relock; not pushing."
else
  git push --quiet \
    --force-with-lease="refs/heads/${relock_branch}:${remote_commit}" \
    origin "HEAD:refs/heads/${relock_branch}"
fi

description="$(pr_description)"
if [[ -z "${open_pr}" ]]; then
  gh pr create \
    --repo "${GITHUB_REPOSITORY}" \
    --base "${base_branch}" \
    --head "${relock_branch}" \
    --title "${title}" \
    --body-file - \
    <<<"${description}"
else
  gh pr edit "${open_pr}" \
    --repo "${GITHUB_REPOSITORY}" \
    --body-file - \
    <<<"${description}"
  echo "Updated pull request #${open_pr}."
fi
