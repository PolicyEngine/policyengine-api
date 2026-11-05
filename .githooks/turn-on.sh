#!/bin/sh
# make install runs this to turn on the hooks in .githooks for the clone, with
# git config core.hooksPath .githooks (api.quality.pre-commit-hook). It
# changes nothing, and says why, when this directory isn't the root of a git
# working tree, when core.hooksPath already names another directory, when the
# clone has hooks of its own (files or symbolic links) that core.hooksPath
# would stop git running, or when git can't write the setting. It always
# exits 0, so make install still installs.
set -u

# Outside a git repository, such as a source archive, there's nothing to do.
prefix=$(git rev-parse --show-prefix 2>/dev/null) || exit 0
if [ -n "$prefix" ]; then
  echo "make install: $(pwd) isn't the root of a git working tree (it is $prefix inside one), so the pre-commit hook isn't turned on." >&2
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

# -L follows symbolic links, both a linked hooks directory and linked hooks.
hooks=$(git rev-parse --git-path hooks)
own=$(find -L "$hooks" -mindepth 1 ! -type d ! -name '*.sample' 2>/dev/null)
if [ -n "$own" ]; then
  echo "make install: the pre-commit hook isn't turned on, because git would then stop running these hooks of the clone's own:
$own
Move them into .githooks, or call .githooks/pre-commit from them, then run git config core.hooksPath .githooks." >&2
  exit 0
fi

if git config core.hooksPath .githooks; then
  echo "make install: turned on the pre-commit hook for every worktree of this clone (core.hooksPath = .githooks)."
else
  echo "make install: git couldn't set core.hooksPath (is .git/config locked by another git command?), so the pre-commit hook isn't turned on. Run make install again, or git config core.hooksPath .githooks." >&2
fi
exit 0
