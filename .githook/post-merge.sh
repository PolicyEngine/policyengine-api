#!/bin/sh


echo "Starting post-merge hook... "


if [ -f .git/MERGE_HEAD ]; then
  echo "This is a merge commit (likely a PR merge)"
else
  echo "This is not a merge commit, exiting."
  exit 0
fi

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "master" ]; then
  echo "Not on master branch ($CURRENT_BRANCH), skipping tag creation."
  exit 0
fi


COMMIT_HASH=$(git rev-parse HEAD)
echo "Current commit: $COMMIT_HASH"


LATEST_TAG=$(git tag | grep "^v" | sort -V | tail -1)
echo "Latest tag found: $LATEST_TAG"


if [ -z "$LATEST_TAG" ]; then
  LATEST_TAG="v0.1.0"
  echo "No tag with 'v' prefix found, defaulting to $LATEST_TAG"
fi


VERSION=${LATEST_TAG#v}
MAJOR=$(echo $VERSION | cut -d. -f1)
MINOR=$(echo $VERSION | cut -d. -f2)
PATCH=$(echo $VERSION | cut -d. -f3)
echo "Parsed version: Major=$MAJOR, Minor=$MINOR, Patch=$PATCH"


PATCH=$((PATCH + 1))
echo "Incremented patch version to $PATCH"


NEW_VERSION="v$MAJOR.$MINOR.$PATCH"
echo "New version tag: $NEW_VERSION"


if git rev-parse "$NEW_VERSION" >/dev/null 2>&1; then
  echo "Tag $NEW_VERSION already exists, skipping tag creation."
  exit 0
fi


echo "Creating tag $NEW_VERSION..."
git tag -a "$NEW_VERSION" -m "Release $NEW_VERSION"


echo "Pushing tag $NEW_VERSION to origin..."
git push origin "$NEW_VERSION"


echo "Post-merge hook completed: Created and pushed tag: $NEW_VERSION"