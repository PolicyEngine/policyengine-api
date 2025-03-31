# Automatic Version Tagging

This repository has an automated process for creating new version tags when the version number is updated in the codebase. This document explains how this system works and how to use it.

## How It Works

When a commit is pushed to the `master` branch, a GitHub Actions workflow automatically:

1. Checks if the `policyengine_api/constants.py` file was modified in the commit
2. If it was modified, extracts the current version number and compares it with the previous version
3. If the version number has changed, checks if a Git tag with this version number already exists
4. If the tag doesn't exist, creates a new annotated tag and pushes it to the repository

## When Tags Are Created

Tags will only be created when:

- The commit is pushed to the `master` branch
- The `policyengine_api/constants.py` file has been changed in that commit
- The VERSION constant in the file has been updated to a new value
- A tag with the new version number doesn't already exist

## Commit Methods

The automatic tagging process works with **any method** of committing code to the repository, including:

- Git command line
- GitHub Desktop
- Pull request merges
- Direct edits via the GitHub web interface
- Any other Git client

## Manual Tagging

If you need to manually create a tag for a specific version, you can use the existing `.github/publish-git-tag.sh` script or run the following commands:

```bash
# Get the current version
VERSION=$(grep -o 'VERSION = "[^"]*"' policyengine_api/constants.py | cut -d'"' -f2)

# Create an annotated tag
git tag -a "$VERSION" -m "Release $VERSION"

# Push the tag
git push origin "$VERSION"
```

## Tag Format

Tags follow the version number format defined in `policyengine_api/constants.py`, which is typically a semantic versioning format (e.g., `3.12.9`).

## Troubleshooting

If tags aren't being created automatically:

1. Check that you're pushing to the `master` branch
2. Verify that `policyengine_api/constants.py` was modified and the VERSION constant was updated
3. Check if the tag already exists (`git tag -l`)
4. Look at the GitHub Actions logs for detailed information about what happened
5. Ensure GitHub Actions has proper permissions to push tags to the repository

## Workflow Logs

The workflow provides detailed logs to help understand what's happening:

- Whether the constants.py file was changed
- The previous and current version numbers
- Whether a version change was detected
- Whether a tag already exists
- The result of the tagging operation

## Workflow Configuration

The workflow is defined in `.github/workflows/auto-tag-release.yml`. You can modify this file if you need to change how automatic tagging works.
