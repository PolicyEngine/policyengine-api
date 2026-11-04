#!/usr/bin/env bash

# Close the tracking issue of a PolicyEngine bundle-update pull request that
# was closed without merging.
#
# Each bundle-update pull request names an issue of its own on the first line
# of its description (rule api.process.pr-tracking-issue; see
# update-policyengine-package.sh). Merging the pull request closes it through
# the Fixes line. Superseded updates are closed without merging, so this
# script, run by close-bundle-update-issue.yml, closes their issues instead.
#
# It closes the issue only when the pull request came from
# auto/update-policyengine-bundle-<version>, was not merged, and the first
# line of its description is "Fixes #N" for an open issue titled
# "Update PolicyEngine bundle to <version>". Otherwise it says why it left
# the issue alone and exits 0. It exits 1 when the issue can't be read or
# closed.
#
# Environment:
#   GITHUB_EVENT_PATH  the pull_request event payload (set by the runner)
#   GITHUB_REPOSITORY  owner/name of this repository (set by the runner)
#   GH_TOKEN           read by gh: a token that can write issues

set -euo pipefail

: "${GITHUB_EVENT_PATH:?GITHUB_EVENT_PATH is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"

branch_prefix="auto/update-policyengine-bundle-"
# ASCII digits only, without a leading zero, as the PR description check reads
# them; a bracket range could match other digits in some locales.
fixes_line='^Fixes #([123456789][0123456789]*)$'

pull_request="$(jq -r '.pull_request.number' "${GITHUB_EVENT_PATH}")"
merged="$(jq -r '.pull_request.merged' "${GITHUB_EVENT_PATH}")"
branch="$(jq -r '.pull_request.head.ref // ""' "${GITHUB_EVENT_PATH}")"
description="$(jq -r '.pull_request.body // ""' "${GITHUB_EVENT_PATH}")"

if [[ "${merged}" == "true" ]]; then
  echo "Pull request #${pull_request} was merged, which closed its issue."
  exit 0
fi
if [[ "${branch}" != "${branch_prefix}"* ]]; then
  echo "Pull request #${pull_request} is not a bundle update (${branch}); nothing to close."
  exit 0
fi
title="Update PolicyEngine bundle to ${branch#"${branch_prefix}"}"

# The first line ends at a line feed or a carriage return; trailing spaces
# and tabs don't count.
first_line="${description%%$'\n'*}"
first_line="${first_line%%$'\r'*}"
while [[ "${first_line}" == *[$' \t'] ]]; do
  first_line="${first_line%?}"
done
if [[ ! "${first_line}" =~ ${fixes_line} ]]; then
  echo "Pull request #${pull_request}'s description names no tracking issue on its first line; nothing to close."
  exit 0
fi
issue="${BASH_REMATCH[1]}"

if ! answer="$(gh api "repos/${GITHUB_REPOSITORY}/issues/${issue}")"; then
  echo "Could not look up issue #${issue} in ${GITHUB_REPOSITORY}." >&2
  exit 1
fi
if [[ "$(jq -r '.pull_request != null' <<<"${answer}")" == "true" ]]; then
  echo "#${issue} is a pull request, not an issue; nothing to close."
  exit 0
fi
issue_title="$(jq -r '.title // ""' <<<"${answer}")"
if [[ "${issue_title}" != "${title}" ]]; then
  echo "Issue #${issue} is titled \"${issue_title}\", not \"${title}\"; leaving it open."
  exit 0
fi
if [[ "$(jq -r '.state // ""' <<<"${answer}")" != "open" ]]; then
  echo "Issue #${issue} is already closed."
  exit 0
fi

gh issue close "${issue}" \
  --repo "${GITHUB_REPOSITORY}" \
  --reason "not planned" \
  --comment "The bundle-update pull request #${pull_request} was closed without merging, so this update won't happen. A later update has an issue of its own."
echo "Closed issue #${issue}, which #${pull_request} named."
