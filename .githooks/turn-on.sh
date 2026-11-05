#!/bin/sh
# make install runs this to turn on the hooks in .githooks for the clone, with
# git config core.hooksPath .githooks (api.quality.pre-commit-hook). It
# changes nothing, and says why, when this directory isn't the root of a git
# working tree, when core.hooksPath already names another directory, or when
# the clone has hooks of its own that core.hooksPath would stop git running.
# It never fails, so make install still installs.
set -u

here=$(pwd -P)
# Outside a git repository, such as a source archive, there's nothing to do.
root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
if [ "$(cd "$root" && pwd -P)" != "$here" ]; then
  echo "make install: $here isn't the root of a git working tree ($root is), so the pre-commit hook isn't turned on." >&2
  exit 0
fi

current=$(git config --get core.hooksPath)
if [ "$current" = ".githooks" ]; then
  exit 0
fi
if [ -n "$current" ]; then
  echo "make install: core.hooksPath is already $current, so the pre-commit hook isn't turned on. Run git config core.hooksPath .githooks to use it instead, or call .githooks/pre-commit from your own hook." >&2
  exit 0
fi

hooks=$(git rev-parse --git-path hooks)
own=$(find "$hooks" -type f ! -name '*.sample' 2>/dev/null)
if [ -n "$own" ]; then
  echo "make install: the pre-commit hook isn't turned on, because git would then stop running these hooks of the clone's own:
$own
Move them into .githooks, or call .githooks/pre-commit from them, then run git config core.hooksPath .githooks." >&2
  exit 0
fi

git config core.hooksPath .githooks &&
  echo "make install: turned on the pre-commit hook for every worktree of this clone (core.hooksPath = .githooks)."
