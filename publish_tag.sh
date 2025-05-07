#!/usr/bin/env bash

# This script handles git tag publishing by adapting the existing approach from the codebase
# It can be run manually or integrated into an automated workflow

set -e

# Check if we're in the repository root
if [ ! -f "setup.py" ] || [ ! -f "policyengine_api/constants.py" ]; then
  echo "Error: This script must be run from the repository root"
  exit 1
fi

# Get the current version
current_version=$(python setup.py --version)
echo "Current version: $current_version"

# Check if this version already exists as a tag
if git rev-parse --verify --quiet "$current_version"; then
  echo "Version $current_version already exists in commit:"
  git --no-pager log -1 "$current_version"
  echo "No need to create a new tag."
  exit 0
fi

# Check if the current version has functional changes from the last tagged version
# (Adapted from .github/has-functional-changes.sh)
IGNORE_DIFF_ON="README.md CONTRIBUTING.md Makefile docs/* .gitignore LICENSE* .github/* data/*"
last_tagged_commit=$(git describe --tags --abbrev=0 --first-parent 2>/dev/null || echo "HEAD~1")

echo "Checking for functional changes since $last_tagged_commit..."
if git diff-index --name-only --exit-code "$last_tagged_commit" -- . $(echo " $IGNORE_DIFF_ON" | sed 's/ / :(exclude)/g'); then
  echo "No functional changes detected since the last tag."
  echo "No need to create a new tag."
  exit 0
else
  echo "Functional changes detected. Proceeding with tag creation."
fi

# Create the changelog if it doesn't exist or needs updating
if [ -f "changelog_entry.yaml" ]; then
  echo "Updating changelog..."
  if command -v build-changelog &>/dev/null; then
    # Use make if available
    if [ -f "Makefile" ] && grep -q "changelog" Makefile; then
      make changelog
    else
      # Manually run the changelog commands (adapted from Makefile)
      build-changelog changelog.yaml --output changelog.yaml --update-last-date --start-from 0.1.0 --append-file changelog_entry.yaml
      build-changelog changelog.yaml --org PolicyEngine --repo policyengine-api --output CHANGELOG.md --template .github/changelog_template.md
      bump-version changelog.yaml setup.py policyengine_api/constants.py
      rm changelog_entry.yaml || true
      touch changelog_entry.yaml
    fi
  else
    echo "Warning: build-changelog not found. Install it with 'pip install yaml-changelog'"
    echo "Skipping changelog update."
  fi
fi

# Create the git tag
echo "Creating git tag $current_version..."
git tag -a "$current_version" -m "Version $current_version"

# Push the tag
echo "Pushing tag to remote..."
git push origin "$current_version"

echo "Tag $current_version successfully published!" 