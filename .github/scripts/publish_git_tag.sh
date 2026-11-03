#!/usr/bin/env bash

# Tag the release commit with the version in pyproject.toml and push that tag.
# A tag that already names the release commit is left as it is, so a rerun of
# the release passes; a tag that names another commit fails the release.

set -euo pipefail

version="$(
    python3 -c 'import sys, tomllib; print(tomllib.load(sys.stdin.buffer).get("project", {}).get("version", ""))' \
        < pyproject.toml
)"
if [[ ! "${version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "ERROR: pyproject.toml's [project] version '${version}' is not a release version" >&2
    exit 1
fi

release_commit="$(git rev-parse HEAD)"
tag_ref="refs/tags/${version}"
# An annotated tag is listed twice; its peeled line (^{}) names the commit.
tagged_commit="$(
    git ls-remote origin "${tag_ref}" "${tag_ref}^{}" \
        | awk -v ref="${tag_ref}" '$2 == ref || $2 == ref "^{}" { commit = $1 } END { print commit }'
)"

if [ -n "${tagged_commit}" ]; then
    if [ "${tagged_commit}" = "${release_commit}" ]; then
        echo "Tag ${version} already names the release commit ${release_commit}"
        exit 0
    fi
    echo "ERROR: tag ${version} names ${tagged_commit}, not the release commit ${release_commit}" >&2
    exit 1
fi

git tag "${version}" "${release_commit}"
git push origin "${tag_ref}"
echo "Pushed tag ${version} for ${release_commit}"
