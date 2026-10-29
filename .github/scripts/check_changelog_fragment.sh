#!/usr/bin/env bash

# Require the pull request to add a changelog fragment the release can read
# (rule api.process.changelog-fragment). The "Check changelog fragment" job in
# .github/workflows/pr.yml runs this on the commit GitHub checks out.
#
# It lists what the pull request changes in the fragment directory
# (changelog.d/) relative to its base, and passes that to
# .github/changelog_fragments.py. That fails unless the pull request adds a
# fragment of its own and every file in the directory is a fragment. Fragments
# already on the base branch belong to the pull requests that added them, so
# editing, deleting or renaming one doesn't count; moving a file the release
# couldn't read into place does.
#
# The comparison starts at the merge base of BASE_SHA and HEAD. For a pull
# request event, GitHub checks out its test merge commit, whose first parent
# is BASE_SHA, so this is exactly what merging the pull request adds to its
# base. Checked out at the pull request's own head, it is what the branch has
# added since it left the base branch.
#
# It also lists the fragments the base branch removed after the pull
# request's branch left it, with the blob each one held; a release removes
# each fragment it builds. A branch that still holds the commits of a lower
# pull request in a stack, squash-merged and released since, would add that
# fragment back with the same text, so it must not count.
#
# Run from the repository root, in a clone with the base branch's history
# (actions/checkout with fetch-depth: 0).
#
# Environment:
#   BASE_SHA  the commit the pull request merges into
#             (github.event.pull_request.base.sha); locally, for example,
#             BASE_SHA=origin/master
#   PYTHON    the Python 3.11+ interpreter to run the check with
#             (default: python3)

set -euo pipefail

base_revision="${BASE_SHA:?BASE_SHA is required: the commit the pull request merges into, such as origin/master}"
python_bin="${PYTHON:-python3}"
fragments_module="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/changelog_fragments.py"

if [[ "$(git rev-parse --is-shallow-repository)" == "true" ]]; then
  echo "::error::This clone is shallow, so it may lack the base commit or the history that leads to it. Check out with fetch-depth: 0."
  exit 1
fi

if ! base_commit="$(git merge-base "${base_revision}" HEAD)"; then
  echo "::error::Could not find a common ancestor of ${base_revision} and HEAD. The clone needs the base branch's history: check out with fetch-depth: 0."
  exit 1
fi

# The module prints its own error annotation when it can't read the directory.
if ! fragment_directory="$("${python_bin}" "${fragments_module}" directory)"; then
  echo "${fragment_directory}"
  exit 1
fi

# The pull request's own head: the second parent of GitHub's test merge
# commit, or HEAD when HEAD is the head itself.
pull_request_head="HEAD"
if git rev-parse --verify --quiet "HEAD^2" >/dev/null \
  && [[ "$(git rev-parse "HEAD^1")" == "$(git rev-parse "${base_revision}^{commit}")" ]]; then
  pull_request_head="HEAD^2"
fi
branch_point="$(git merge-base "${base_revision}" "${pull_request_head}")"

released_fragments_file="$(mktemp)"
trap 'rm -f "${released_fragments_file}"' EXIT
git log --diff-filter=D --no-renames --raw --no-abbrev -z --format= \
  "${branch_point}..${base_revision}" -- "${fragment_directory}" >"${released_fragments_file}"

git diff --find-renames --name-status -z "${base_commit}" HEAD -- "${fragment_directory}" \
  | "${python_bin}" "${fragments_module}" check-pull-request \
    --released-fragments "${released_fragments_file}"
